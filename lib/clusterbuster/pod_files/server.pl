#!/usr/bin/perl
use Socket;
use POSIX;
use strict;
use Time::Piece;
use Time::HiRes qw(gettimeofday usleep);
use File::Basename;
my ($dir) = $ENV{'BAK_CONFIGMAP'};
require "$dir/clientlib.pl";

$SIG{TERM} = sub { POSIX::_exit(0); };
my ($basetime, $baseoffset, $listen_port, $container, $msgSize, $ts, $expected_clients) = @ARGV;
$basetime += $baseoffset;

timestamp("Clusterbuster server starting");
my $sockaddr = "S n a4 x8";
socket(SOCK, AF_INET, SOCK_STREAM, getprotobyname('tcp')) || die "socket: $!";
$SIG{TERM} = sub { close SOCK; kill 'KILL', -1; POSIX::_exit(0); };
setsockopt(SOCK,SOL_SOCKET, SO_REUSEADDR, pack("l",1)) || die "setsockopt reuseaddr: $!\n";
setsockopt(SOCK,SOL_SOCKET, SO_KEEPALIVE, pack("l",1)) || die "setsockopt keepalive: $!\n";
bind(SOCK, pack($sockaddr, AF_INET, $listen_port, "\0\0\0\0")) || die "bind: $!\n";
listen(SOCK, 5) || die "listen: $!";
my $mysockaddr = getsockname(SOCK);
my ($junk, $port, $addr) = unpack($sockaddr, $mysockaddr);
die "can't get port $port: $!\n" if ($port ne $listen_port);
timestamp("Listening on port $listen_port");
$SIG{CHLD} = 'IGNORE';

print STDERR "Expect $expected_clients clients\n";
while ($expected_clients != 0) {
    accept(CLIENT, SOCK) || next;
    if ((my $child = fork()) == 0) {
	close(SOCK);
	$SIG{TERM} = sub { close CLIENT; POSIX::_exit(0); };
	my $peeraddr = getpeername(CLIENT);
	my ($port, $addr) = sockaddr_in($peeraddr);
	my $peerhost = gethostbyaddr($addr, AF_INET);
	my $peeraddr = inet_ntoa($addr);
	timestamp("Accepted connection from $peerhost ($peeraddr) on $port!");
	my ($consec_empty) = 0;
	my $buffer;
	my $nread;
	my $ntotal = 0;
	my $nwrite;
	while (1) {
	    while ($ntotal < $msgSize && ($nread = sysread(CLIENT, $buffer, $msgSize, $ntotal)) > 0) {
		$ntotal += $nread;
		$consec_empty=0;
	    }
	    if ($nread < 0) {
		die "Write failed: $!\n";
	    }
	    if ($ntotal == 0) {
	        if ($consec_empty > 1) {
		    timestamp("Exiting $port");
		    exit(0);
		}
	        $consec_empty++;
	    }
	    while ($ntotal > 0 && ($nwrite = syswrite(CLIENT, $buffer, $ntotal)) > 0) {
		$ntotal -= $nwrite;
	    }
	    if ($nwrite < 0) {
		die "Write failed: $!\n";
	    }
	}
    } else {
	close(CLIENT);
	$expected_clients--;
    }
}
timestamp("Waiting for all clients to exit:");
while ((my $pid = wait()) >= 0) {
    timestamp("   $pid");
}
timestamp("Done!");

finish(1);
