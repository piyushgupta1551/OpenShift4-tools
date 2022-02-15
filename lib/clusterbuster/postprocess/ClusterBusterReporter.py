#!/usr/bin/env python3

# Copyright 2022 Robert Krawitz/Red Hat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import sys
import textwrap
from copy import deepcopy


class ClusterBusterReporter:
    def are_clients_all_on_same_node(self):
        node = None
        for obj in self._jdata['api_objects']:
            if obj['kind'] == 'Pod' and 'clusterbuster-client' in obj['labels'] and obj['labels']['clusterbuster-client']:
                if not node:
                    node = obj['nodeName']
                elif obj['nodeName'] != node:
                    return False
        return True

    def find_node_for_pod(self, namespace: str, pod: str):
        for obj in self._jdata['api_objects']:
            if obj['kind'] == 'Pod' and obj['namespace'] == namespace and obj['name'] == pod:
                return obj['nodeName']
        return None

    def __init__(self, jdata: dict, report_format: str):
        self._jdata = deepcopy(jdata)
        self._format = report_format
        self._all_clients_are_on_the_same_node = self.are_clients_all_on_same_node()
        self._summary = {'cpu_time': 0,
                         'runtime': 0,
                         'total_instances': 0}
        self._rows = []
        self._timeline_vars = []
        self._accumulator_vars = []
        self._summary_indent = 4
        self._verbose_indent = 0
        self.initialize_timeline_vars(['data_start', 'data_end', 'pod_start', 'pod_create'])
        self.initialize_accumulators(['user_cpu_time', 'system_cpu_time', 'cpu_time', 'data_elapsed_time'])

    def initialize_timeline_vars(self, vars_to_update: list):
        self._timeline_vars.extend(vars_to_update)

    def initialize_accumulators(self, accumulators: list):
        self._accumulator_vars.extend(accumulators)

    def set_header_components(self, headers: list):
        self._header = headers

    def row_name(self, row: dict):
        return f'{row["namespace"]}~{row["pod"]}~{row["container"]}~{row.get("process_id", 0):#07d}'

    def update_timeline_val(self, var: str, row, summary: dict):
        components = var.split('.', 1)
        if len(components) > 1:
            if components[0] not in summary:
                summary[components[0]] = {}
            self.update_timeline_val(components[1], row[components[0]], summary[components[0]])
        else:
            row_val = row[f'{var}_time_offset_from_base']
            if f'first_{var}' not in summary or row_val < summary[f'first_{var}']:
                summary[f'first_{var}'] = row_val
            if f'last_{var}' not in summary or row_val > summary[f'last_{var}']:
               summary[f'last_{var}'] = row_val

    def update_accumulator_val(self, var: str, row, summary, rowhash: dict):
        components = var.split('.', 1)
        if len(components) > 1:
            if components[0] not in summary:
                summary[components[0]] = {}
            if components[0] not in rowhash:
                rowhash[components[0]] = {}
            self.update_accumulator_val(components[1], row[components[0]], summary[components[0]], rowhash[components[0]])
        else:
            row_val = row[var]
            if var not in summary:
                summary[var] = 0
            if f'max_{var}' not in summary:
                summary[f'max_{var}'] = row_val
                summary[f'min_{var}'] = row_val
            else:
                if (row_val > summary[f'max_{var}']):
                    summary[f'max_{var}'] = row_val
                if (row_val < summary[f'min_{var}']):
                    summary[f'min_{var}'] = row_val
            summary[var] += row_val
            rowhash[var] = row_val

    def create_row(self, row: dict):
        rowhash = {}
        rowhash['namespace'] = row['namespace']
        rowhash['pod'] = row['pod']
        rowhash['container'] = row['container']
        rowhash['node'] = self.find_node_for_pod(namespace=row['namespace'], pod=row['pod'])
        rowhash['process_id'] = row['process_id']
        self._summary['total_instances'] += 1
        for var in self._timeline_vars:
            self.update_timeline_val(var, row, self._summary)
        for accumulator in self._accumulator_vars:
            self.update_accumulator_val(accumulator, row, self._summary, rowhash)
        self._rows.append(rowhash)
        return len(self._rows)-1

    def initialize_summary(self):
        self._summary['elapsed_time_average'] = self._summary['data_elapsed_time'] / self._summary['total_instances']
        self._summary['pod_create_span'] = self._summary['last_pod_create'] - self._summary['first_pod_create']
        if self._all_clients_are_on_the_same_node:
            self._summary['data_run_span'] = self._summary['last_data_end'] - self._summary['first_data_start']
            self._summary['pod_start_span'] = self._summary['last_pod_start'] - self._summary['first_pod_start']
            self._summary['overlap_error'] = ((((self._summary['last_data_start'] - self._summary['first_data_start']) +
                                         (self._summary['last_data_end'] - self._summary['first_data_end'])) / 2) /
                                        self._summary['elapsed_time_average'])
        else:
            self._summary['data_run_span'] = self._summary['elapsed_time_average']

    def generate_summary(self, results:dict):
        results['Total Clients'] = self._summary['total_instances']
        results['Elapsed Time Average'] = round(self._summary['elapsed_time_average'], 3)
        results['Pod creation span'] = round(self._summary['pod_create_span'], 5)
        results['User CPU seconds'] = round(self._summary['user_cpu_time'], 3)
        results['System CPU seconds'] = round(self._summary['system_cpu_time'], 3)
        results['CPU seconds'] = round(self._summary['cpu_time'], 5)
        if self._all_clients_are_on_the_same_node:
            results['CPU utilization'] = round(self._summary['cpu_time'] / self._summary['data_run_span'], 5)
            results['First run start'] = round(self._summary['first_data_start'], 3)
            results['First run end'] = round(self._summary['first_data_end'], 3)
            results['Last run start'] = round(self._summary['last_data_start'], 3)
            results['Last run end'] = round(self._summary['last_data_end'], 3)
            results['Net elapsed time'] = round(self._summary['data_run_span'], 3)
            results['Overlap error'] = round(self._summary['overlap_error'], 5)
            results['Pod start span'] = round(self._summary['pod_start_span'], 5)
#        else:
#            print(f'''
#    *** Run start/end not available when client pods are not all on the same node ***''')

    def generate_row(self, results, row):
        pass

    def compute_report_width(self, results, indentation=4, integer_width=0):
        width = 0
        integer_width = 0
        for key in results:
            if isinstance(results[key], dict):
                fwidth, nwidth = self.compute_report_width(results[key], indentation=indentation)
                fwidth += indentation
            else:
                if isinstance(results[key], float):
                    nwidth = len(str(int(results[key])))
                elif isinstance(results[key], int):
                    nwidth = len(str(results[key]))
                else:
                    nwidth = 0
                fwidth = len(key)
            if fwidth > width:
                width = fwidth
            if nwidth > integer_width:
                integer_width = nwidth
        return [width, integer_width]

    def print_subreport(self, results, headers: list, key_column=0, value_column=0, depth_indentation=4, integer_width=0):
        header_keys = []
        value_keys = []
        for key in results.keys():
            if key in results:
                if isinstance(results[key], dict):
                    header_keys.append(key)
                else:
                    value_keys.append(key)

        header_name = None
        if key_column > 0 and len(headers):
            headers = deepcopy(headers)
            header_name = headers.pop(0)
        for key in header_keys:
            if header_name:
                print(f'{" " * key_column}{header_name}: {key}:')
            else:
                print(f'{" " * key_column} {key}:')
            self.print_subreport(results[key], headers, key_column = key_column + depth_indentation, value_column=value_column, depth_indentation=depth_indentation, integer_width=integer_width)
        for key in value_keys:
            value = results[key]
            if isinstance(value, int):
                integer_indent = integer_width - len(str(value))
            elif isinstance(value, float):
                integer_indent = integer_width - len(str(int(value)))
            else:
                integer_indent = 0
            value = str(value)
            print(f'{" " * key_column}{key}: {" " * (value_column + integer_indent  - key_column - len(key))}{value}')
        if len(header_keys) == 0:
            print('')

    def make_header_tree(self, results:dict, row:dict, headers:list):
        if len(headers) > 1:
            hdr = headers.pop(0)
            if row[hdr] not in results:
                results[row[hdr]] = {}
            self.make_header_tree(results[row[hdr]], row, headers)

    def create_text_report(self):
        results = {}
        overview_keys = ['Workload', 'Job UUID', 'Run host', 'Kubernetes version', 'OpenShift version', 'Command line']
        results['Overview'] = {}
        results['Overview']['Workload'] = self._jdata['metadata']['workload']
        results['Overview']['Job UUID'] = self._jdata['metadata']['run_uuid']
        results['Overview']['Run host'] = self._jdata['metadata']['runHost']
        results['Overview']['Kubernetes version'] = self._jdata['metadata']['kubernetes_version']['serverVersion']['gitVersion']
        if 'openshiftVersion' in self._jdata['metadata']['kubernetes_version']:
            results['Overview']['OpenShift Version'] = self._jdata['metadata']['kubernetes_version']['openshiftVersion']
        results['Overview']['Command line'] = textwrap.fill(' '.join(self._jdata['metadata']['expanded_command_line']),
                                                            width=72, subsequent_indent='                ',
                                                            break_long_words=False, break_on_hyphens=False)

        if self._format == 'verbose':
            results['Detail'] = {}
            self._rows.sort(key=self.row_name)
            for row in self._rows:
                self.make_header_tree(results['Detail'], row, deepcopy(self._header))
                self.generate_row(results['Detail'], row)
        results['Summary'] = {}
        self.generate_summary(results['Summary'])
        key_width, integer_width = self.compute_report_width(results)
        self.print_subreport(results, self._header, key_column=0, value_column=key_width, integer_width=integer_width)

    def create_report(self):
        if 'Results' in self._jdata:
            rows = self._jdata['Results']
            for row in rows:
                self.create_row(row)

            self.initialize_summary()

            if self._format == 'json-summary':
                answer = {
                    'summary': self._summary,
                    'metadata': self._jdata['metadata'],
                    }
                json.dump(answer, sys.stdout, sort_keys=True, indent=4)
            elif self._format == 'json':
                answer = {
                    'summary': self._summary,
                    'metadata': self._jdata['metadata'],
                    'rows': self._rows
                    }
                json.dump(answer, sys.stdout, sort_keys=True, indent=4)
            elif self._format == 'json-verbose':
                answer = deepcopy(self._jdata)
                answer['processed_results'] = {
                    'summary': self._summary,
                    'rows': self._rows
                    }
                json.dump(answer, sys.stdout, sort_keys=True, indent=4)
            else:
                self.create_text_report()