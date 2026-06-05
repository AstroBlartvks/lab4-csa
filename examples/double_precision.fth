\ 64-bit arithmetic: compute 20! using (lo hi) pair in variables

variable dlo  variable dhi
variable i
variable leading

variable _n  variable _lo_lo  variable _lo_hi
variable _prod_lo  variable _prod_hi
variable _sum  variable _carry

: lo_uge
  over 0 < over 0 < =
  if >= else drop 0 < then
;

: dmul_n
  _n !
  dlo @ 0xFFFF and _lo_lo !
  dlo @ 0xFFFF0000 and 0x10000 /
  dup 0 < if 0x10000 + then
  _lo_hi !
  _lo_lo @ _n @ * _prod_lo !
  _lo_hi @ _n @ * _prod_hi !
  _prod_hi @ 0xFFFF and 0x10000 * _prod_lo @ + _sum !
  _sum @ _prod_lo @ lo_uge invert _carry !
  _prod_hi @ 0x10000 / _carry @ negate + dhi @ _n @ * + dhi !
  _sum @ dlo !
;

variable p0lo   variable p1lo   variable p2lo   variable p3lo
variable p4lo   variable p5lo   variable p6lo   variable p7lo
variable p8lo   variable p9lo   variable p10lo  variable p11lo
variable p12lo  variable p13lo  variable p14lo  variable p15lo
variable p16lo  variable p17lo  variable p18lo
variable p0hi   variable p1hi   variable p2hi   variable p3hi
variable p4hi   variable p5hi   variable p6hi   variable p7hi
variable p8hi   variable p9hi   variable p10hi  variable p11hi
variable p12hi  variable p13hi  variable p14hi  variable p15hi
variable p16hi  variable p17hi  variable p18hi

: init_pow
  1 p0lo !  0 p0hi !
  10 p1lo !  0 p1hi !
  100 p2lo !  0 p2hi !
  1000 p3lo !  0 p3hi !
  10000 p4lo !  0 p4hi !
  100000 p5lo !  0 p5hi !
  1000000 p6lo !  0 p6hi !
  10000000 p7lo !  0 p7hi !
  100000000 p8lo !  0 p8hi !
  1000000000 p9lo !  0 p9hi !
  1410065408 p10lo !  2 p10hi !
  1215752192 p11lo !  23 p11hi !
  -727379968 p12lo !  232 p12hi !
  1316134912 p13lo !  2328 p13hi !
  276447232 p14lo !  23283 p14hi !
  -1530494976 p15lo !  232830 p15hi !
  1874919424 p16lo !  2328306 p16hi !
  1569325056 p17lo !  23283064 p17hi !
  -1486618624 p18lo !  232830643 p18hi !
;

variable pow_lo  variable pow_hi

: dge_pow
  dhi @ pow_hi @ = if
    dlo @ pow_lo @ lo_uge
  else
    dhi @ pow_hi @ >
  then
;

: dsub_pow
  dlo @ pow_lo @ lo_uge invert >r
  dlo @ pow_lo @ -
  dhi @ pow_hi @ - r> negate -
  dhi ! dlo !
;

: emit_pow
  0
  begin dge_pow while dsub_pow 1+ repeat
  dup 0 = leading @ and if
    drop
  else
    0 leading !
    48 + emit
  then
;

: d.
  1 leading !
  p18lo @ pow_lo !  p18hi @ pow_hi !  emit_pow
  p17lo @ pow_lo !  p17hi @ pow_hi !  emit_pow
  p16lo @ pow_lo !  p16hi @ pow_hi !  emit_pow
  p15lo @ pow_lo !  p15hi @ pow_hi !  emit_pow
  p14lo @ pow_lo !  p14hi @ pow_hi !  emit_pow
  p13lo @ pow_lo !  p13hi @ pow_hi !  emit_pow
  p12lo @ pow_lo !  p12hi @ pow_hi !  emit_pow
  p11lo @ pow_lo !  p11hi @ pow_hi !  emit_pow
  p10lo @ pow_lo !  p10hi @ pow_hi !  emit_pow
  p9lo  @ pow_lo !  p9hi  @ pow_hi !  emit_pow
  p8lo  @ pow_lo !  p8hi  @ pow_hi !  emit_pow
  p7lo  @ pow_lo !  p7hi  @ pow_hi !  emit_pow
  p6lo  @ pow_lo !  p6hi  @ pow_hi !  emit_pow
  p5lo  @ pow_lo !  p5hi  @ pow_hi !  emit_pow
  p4lo  @ pow_lo !  p4hi  @ pow_hi !  emit_pow
  p3lo  @ pow_lo !  p3hi  @ pow_hi !  emit_pow
  p2lo  @ pow_lo !  p2hi  @ pow_hi !  emit_pow
  p1lo  @ pow_lo !  p1hi  @ pow_hi !  emit_pow
  0
  p0lo @ pow_lo !  p0hi @ pow_hi !
  begin dge_pow while dsub_pow 1+ repeat
  48 + emit
;

init_pow

1 dlo !  0 dhi !
2 i !
begin i @ 20 <= while
  i @ dmul_n
  i @ 1 + i !
repeat

d. cr
