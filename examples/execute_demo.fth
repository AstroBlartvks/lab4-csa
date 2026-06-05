\ Demonstration of execution tokens: ' (tick) and execute

: double 2 * ;
: triple 3 * ;

: apply  ( n xt -- result )  execute ;

10 ' double apply . cr
10 ' triple apply . cr

variable ops
' double ops !

5 ops @ execute . cr
