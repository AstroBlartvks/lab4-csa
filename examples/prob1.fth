\ Euler problem 4: largest palindrome product of two 3-digit numbers
\ Answer: 906609 = 913 * 993

variable best
variable i
variable j
variable _n

: not_palindrome  ( n -- flag )  \ returns 0 if IS palindrome, nonzero if NOT
  _n !
  _n @ 100000 /  _n @ 10 mod  <>
  _n @ 10000 / 10 mod  _n @ 10 / 10 mod  <> or
  _n @ 1000  / 10 mod  _n @ 100 / 10 mod  <> or
;

0 best !
999 i !
begin i @ 100 >= while
  i @ j !
  begin j @ 100 >= while
    i @ j @ *
    dup best @ <= if
      drop 100 j !
    else
      dup not_palindrome if
        drop
      else
        best !
      then
    then
    j @ 1 - j !
  repeat
  i @ 1 - i !
repeat

best @ . cr
