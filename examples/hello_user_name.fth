." What is your name?" cr
variable buf 32 allot
variable len

( читаем символы до \n )
begin
  key dup 10 <>
while
  buf len @ + !
  len @ 1 + len !
repeat
drop

." Hello, "

( выводим buf как строку длиной len символов )
0
begin
  dup len @ <
while
  buf over + @ emit
  1 +
repeat
drop

." !" cr
