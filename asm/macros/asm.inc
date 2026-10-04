	/* Native pointer tables; integer operands retain their original width. */
	.macro data_ptr value:req
#ifdef PORTABLE_64BIT
	.8byte \value
#else
	.int \value
#endif
	.endm

	.macro data_ptr_align
#ifdef PORTABLE_64BIT
	.balign 8
#else
	.balign 4
#endif
	.endm

	.macro inc x:req
	.set \x, \x + 1
	.endm

	.macro enum_start x=0
	.set __enum__, \x
	.endm

	.macro enum constant:req
	.equiv \constant, __enum__
	inc __enum__
	.endm
