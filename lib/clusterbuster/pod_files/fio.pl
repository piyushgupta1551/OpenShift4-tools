#!/usr/bin/perl

use Socket;
use POSIX;
use strict;
use Time::Piece;
use Time::HiRes qw(gettimeofday usleep);
use File::Path qw(make_path remove_tree);
use Sys::Hostname;
use File::Basename;
my ($dir) = $ENV{'BAK_CONFIGMAP'};
require "$dir/clientlib.pl";

our ($namespace, $container, $basetime, $baseoffset, $poddelay, $crtime, $exit_at_end, $synchost, $syncport, $loghost, $logport,
     $processes, $rundir, $runtime, $jobfiles_dir, $fio_blocksizes, $fio_patterns, $fio_generic_args) = @ARGV;

my ($data_start_time, $data_end_time);
$SIG{TERM} = sub() { docleanup() };
$basetime += $baseoffset;
$crtime += $baseoffset;
my ($start_time) = xtime();

my ($pod) = hostname;
my ($localrundir) = "$rundir/$pod/$$";

sub removeRundir() {
    if (-d "$localrundir") {
	open(CLEANUP, "-|", "rm -rf '$localrundir'");
	while (<CLEANUP>) {
	    1;
	}
	close(CLEANUP);
    }
}

sub docleanup()  {
    removeRundir();
    kill 'KILL', -1;
    POSIX::_exit(0);
}

removeRundir();

if (! make_path($localrundir)) {
    timestamp("Cannot create run directory $localrundir: $!");
}
if (! chdir($localrundir)) {
    timestamp("Cannot cd $localrundir: $!");
    exit(1);
}

sub runit(;$) {
    my ($jobfile) = @_;
    my ($firsttime) = 1;
    my ($avgcpu) = 0;
    my ($weight) = .25;
    my ($icputime);
    my ($interval) = 5;
    my ($dstime) = xtime();
    my (@results);
    my ($data_start_time);

    my $delaytime = $basetime + $poddelay - $dstime;
    if ($delaytime > 0) {
	timestamp("Sleeping $delaytime seconds to synchronize");
	usleep($delaytime * 1000000);
    }
    my (@sizes) = split(/ +/, $fio_blocksizes);
    my (@patterns) = split(/ +/, $fio_patterns);
    my ($ucpu0, $scpu0) = cputime();
    my ($jobidx) = 1;
    my ($jstring) = <<'EOF';
"%s": {
  "job_elapsed_time": %f,
  "job_user_cpu_time": %f,
  "job_system_cpu_time": %f,
  "job_cpu_time": %f,
  "job_results": %s
}
EOF
    timestamp("Sizes: " . join(" ", @sizes));
    timestamp("Patterns: " . join(" ", @patterns));
    foreach my $size (@sizes) {
	foreach my $pattern (@patterns) {
	    my ($jobname) = sprintf("%03d-%s-%d", $jobidx, $pattern, $size);
	    do_sync($synchost, $syncport);
	    if ($jobidx == 1) {
		timestamp("Running...");
		$data_start_time = xtime();
	    }
	    my ($answer0) = '';
	    timestamp("fio --rw=$pattern --bs=$size $fio_generic_args --output-format=json+ $jobfile");
	    my ($jtime0) = xtime();
	    my ($jucpu0, $jscpu0) = cputime();
	    open(RUN, "-|", "fio --rw=$pattern --bs=$size $fio_generic_args --output-format=json+ $jobfile | jq -c .") || die "Can't run fio: $!\n";
	    while (<RUN>) {
		$answer0 .= "$_";
	    }
	    close(RUN);
	    my ($jtime1) = xtime();
	    my ($jucpu1, $jscpu1) = cputime();
	    $jtime1 -= $jtime0;
	    $jucpu1 -= $jucpu0;
	    $jscpu1 -= $jscpu0;
	    push @results, sprintf($jstring, $jobname, $jtime1, $jucpu1, $jscpu1, $jucpu1 + $jscpu1, $answer0);
	    $jobidx++;
	}
    }
    my ($data_end_time) = xtime();
    my ($ucpu1, $scpu1) = cputime();
    $ucpu1 -= $ucpu0;
    $scpu1 -= $scpu0;
    my ($all_results) = '{' . join(",\n", @results) . '}';
    my ($fstring) = <<'EOF';
{
  "application": "clusterbuster-json",
  "namespace": "%s",
  "pod": "%s",
  "container": "%s",
  "process_id": %d,
  "pod_create_time_offset_from_base": %f,
  "pod_start_time_offset_from_base": %f,
  "data_start_time_offset_from_base": %f,
  "data_end_time_offset_from_base": %f,
  "data_elapsed_time": %f,
  "user_cpu_time": %f,
  "system_cpu_time": %f,
  "cpu_time": %f,
  "results": %s
}
EOF
    $fstring =~ s/[ \n]+//g;
    my ($answer) = sprintf($fstring, $namespace, $pod, $container, $$, $crtime - $basetime,
			   $start_time - $basetime, $data_start_time - $basetime,
			   $data_end_time - $basetime, $data_end_time - $data_start_time,
			   $ucpu1, $scpu1, $ucpu1 + $scpu1, $all_results);

    do_sync($synchost, $syncport, $answer);
    if ($logport > 0) {
	do_sync($loghost, $logport, $answer);
    }
}

sub get_jobfiles($) {
    my ($dir) = @_;
    opendir DIR, $dir || die "Can't find job files in $dir: #!\n";

    my @files = map { "$dir/$_" } grep { -f "$dir/$_" } sort readdir DIR;
    closedir DIR;
    print STDERR "get_jobfiles($dir) => @files\n";
    return @files;
}

my (@jobfiles) = get_jobfiles($jobfiles_dir);

sub runall() {
    if ($#jobfiles >= 0) {
	foreach my $file (@jobfiles) {
	    runit($file)
	}
    } else {
        runit()
    }
}

if ($processes > 1) {
    for (my $i = 0; $i < $processes; $i++) {
        if ((my $child = fork()) == 0) {
            runall();
	    docleanup();
            exit(0);
        }
    }
} else {
    runall();
}

finish();
