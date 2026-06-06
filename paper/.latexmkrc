my $texbin = '/Library/TeX/texbin';
$ENV{'PATH'} = "$texbin:$ENV{'PATH'}" if -d $texbin;
