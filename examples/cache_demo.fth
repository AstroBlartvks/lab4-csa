\ Cache demonstration: cold miss vs hot hit
\ Array of 16 words; two summation passes to show cache effect

variable arr
15 allot

variable i
variable sum

\ Fill arr[0..15] with 1..16
0 i !
begin i @ 16 < while
  i @ 1 +        ( value = i+1 )
  arr i @ +      ( addr = arr + i )
  !
  i @ 1 + i !
repeat

\ Cold pass: first traversal (cache MISS)
0 sum !
0 i !
begin i @ 16 < while
  arr i @ + @ sum @ + sum !
  i @ 1 + i !
repeat
sum @ . cr

\ Hot pass: second traversal (cache HIT)
0 sum !
0 i !
begin i @ 16 < while
  arr i @ + @ sum @ + sum !
  i @ 1 + i !
repeat
sum @ . cr
