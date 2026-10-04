	.include "asm/macros/asm.inc"
	.section script_data, "aw"

	.align 2
	data_ptr_align
gMysteryEventScriptCmdTable::
	data_ptr MEScrCmd_nop                 /* 0x00*/
	data_ptr MEScrCmd_checkcompat         /* 0x01*/
	data_ptr MEScrCmd_end                 /* 0x02*/
	data_ptr MEScrCmd_setmsg              /* 0x03*/
	data_ptr MEScrCmd_setstatus           /* 0x04*/
	data_ptr MEScrCmd_runscript           /* 0x05*/
	data_ptr MEScrCmd_initramscript       /* 0x06*/
	data_ptr MEScrCmd_setenigmaberry      /* 0x07*/
	data_ptr MEScrCmd_giveribbon          /* 0x08*/
	data_ptr MEScrCmd_givenationaldex     /* 0x09*/
	data_ptr MEScrCmd_addrareword         /* 0x0a*/
	data_ptr MEScrCmd_setrecordmixinggift /* 0x0b*/
	data_ptr MEScrCmd_givepokemon         /* 0x0c*/
	data_ptr MEScrCmd_addtrainer          /* 0x0d*/
	data_ptr MEScrCmd_enableresetrtc      /* 0x0e*/
	data_ptr MEScrCmd_checksum            /* 0x0f*/
	data_ptr MEScrCmd_crc                 /* 0x10*/
gMysteryEventScriptCmdTableEnd::
