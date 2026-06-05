variable arr 32 allot
variable count
variable tmp
variable swapped

( read_num -- читает цифры до \n, возвращает число )
: read_num
  0
  begin
    key dup 10 <>
  while
    48 -
    swap 10 * swap +
  repeat
  drop
;

( read_all -- читает числа пока не EOF )
: read_all
  begin
    0xFFFFFFF1 @
  while
    read_num
    arr count @ + !
    count @ 1 + count !
  repeat
;

( swap_pair i -- меняет arr[i] и arr[i+1] )
: swap_pair
  dup arr + @ tmp !
  dup 1 + arr + @ over arr + !
  tmp @ swap 1 + arr + !
;

( bubble_pass -- один проход, пишет в swapped 1 если был обмен )
: bubble_pass
  0 swapped !
  0
  begin
    dup count @ 1 - <
  while
    dup arr + @
    over 1 + arr + @
    > if
      dup swap_pair
      1 swapped !
    then
    1 +
  repeat
  drop
;

( sort )
: sort
  begin bubble_pass swapped @ 0= until
;

( print_all )
: print_all
  0
  begin
    dup count @ <
  while
    dup arr + @ . cr
    1 +
  repeat
  drop
;

read_all
sort
print_all
