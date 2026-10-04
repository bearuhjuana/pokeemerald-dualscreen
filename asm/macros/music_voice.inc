	/* Match native ToneData/MP2KInstrument pointer alignment and 24-byte
	   stride on LP64; preserve the original 12-byte GBA voice records. */
	.macro _voice_word value:req
#ifdef PORTABLE_64BIT
	.space 4
	.8byte \value
#else
	.int \value
#endif
	.endm

	.macro _voice_tail_padding
#ifdef PORTABLE_64BIT
	.space 4
#endif
	.endm

	.macro voice_directsound base_midi_key:req, pan:req, sample_data_pointer:req, attack:req, decay:req, sustain:req, release:req
	.byte 0
	_voice_directsound \base_midi_key, \pan, \sample_data_pointer, \attack, \decay, \sustain, \release
	.endm

	.macro voice_directsound_no_resample base_midi_key:req, pan:req, sample_data_pointer:req, attack:req, decay:req, sustain:req, release:req
	.byte 8
	_voice_directsound \base_midi_key, \pan, \sample_data_pointer, \attack, \decay, \sustain, \release
	.endm

	.macro voice_directsound_alt base_midi_key:req, pan:req, sample_data_pointer:req, attack:req, decay:req, sustain:req, release:req
	.byte 16
	_voice_directsound \base_midi_key, \pan, \sample_data_pointer, \attack, \decay, \sustain, \release
	.endm

	.macro _voice_directsound base_midi_key:req, pan:req, sample_data_pointer:req, attack:req, decay:req, sustain:req, release:req
	.byte \base_midi_key
	.byte 0
	.if \pan != 0
	.byte (0x80 | \pan)
	.else
	.byte 0
	.endif
	_voice_word \sample_data_pointer
	.byte \attack
	.byte \decay
	.byte \sustain
	.byte \release
	_voice_tail_padding
	.endm

	.macro voice_square_1 base_midi_key:req, pan:req, sweep:req, duty_cycle:req, attack:req, decay:req, sustain:req, release:req
	_voice_square_1 1, \base_midi_key, \pan, \sweep, \duty_cycle, \attack, \decay, \sustain, \release
	.endm

	.macro voice_square_1_alt base_midi_key:req, pan:req, sweep:req, duty_cycle:req, attack:req, decay:req, sustain:req, release:req
	_voice_square_1 9, \base_midi_key, \pan, \sweep, \duty_cycle, \attack, \decay, \sustain, \release
	.endm

	.macro _voice_square_1 type:req, base_midi_key:req, pan:req, sweep:req, duty_cycle:req, attack:req, decay:req, sustain:req, release:req
	.byte \type
	.byte \base_midi_key
	.if \pan != 0
	.byte (0x80 | \pan)
	.else
	.byte 0
	.endif
	.byte \sweep
	_voice_word (\duty_cycle & 0x3)
	.byte (\attack  & 0x7)
	.byte (\decay   & 0x7)
	.byte (\sustain & 0xF)
	.byte (\release & 0x7)
	_voice_tail_padding
	.endm

	.macro voice_square_2 base_midi_key:req, pan:req, duty_cycle:req, attack:req, decay:req, sustain:req, release:req
	_voice_square_2 2, \base_midi_key, \pan, \duty_cycle, \attack, \decay, \sustain, \release
	.endm

	.macro voice_square_2_alt base_midi_key:req, pan:req, duty_cycle:req, attack:req, decay:req, sustain:req, release:req
	_voice_square_2 10, \base_midi_key, \pan, \duty_cycle, \attack, \decay, \sustain, \release
	.endm

	.macro _voice_square_2 type:req, base_midi_key:req, pan:req, duty_cycle:req, attack:req, decay:req, sustain:req, release:req
	.byte \type
	.byte \base_midi_key
	.if \pan != 0
	.byte (0x80 | \pan)
	.else
	.byte 0
	.endif
	.byte 0
	_voice_word (\duty_cycle & 0x3)
	.byte (\attack  & 0x7)
	.byte (\decay   & 0x7)
	.byte (\sustain & 0xF)
	.byte (\release & 0x7)
	_voice_tail_padding
	.endm

	.macro voice_programmable_wave base_midi_key:req, pan:req, wave_samples_pointer:req, attack:req, decay:req, sustain:req, release:req
	_voice_programmable_wave 3, \base_midi_key, \pan, \wave_samples_pointer, \attack, \decay, \sustain, \release
	.endm

	.macro voice_programmable_wave_alt base_midi_key:req, pan:req, wave_samples_pointer:req, attack:req, decay:req, sustain:req, release:req
	_voice_programmable_wave 11, \base_midi_key, \pan, \wave_samples_pointer, \attack, \decay, \sustain, \release
	.endm

	.macro _voice_programmable_wave type:req, base_midi_key:req, pan:req, wave_samples_pointer:req, attack:req, decay:req, sustain:req, release:req
	.byte \type
	.byte \base_midi_key
	.if \pan != 0
	.byte (0x80 | \pan)
	.else
	.byte 0
	.endif
	.byte 0
	_voice_word \wave_samples_pointer
	.byte (\attack  & 0x7)
	.byte (\decay   & 0x7)
	.byte (\sustain & 0xF)
	.byte (\release & 0x7)
	_voice_tail_padding
	.endm

	.macro voice_noise base_midi_key:req, pan:req, period:req, attack:req, decay:req, sustain:req, release:req
	_voice_noise 4, \base_midi_key, \pan, \period, \attack, \decay, \sustain, \release
	.endm

	.macro voice_noise_alt base_midi_key:req, pan:req, period:req, attack:req, decay:req, sustain:req, release:req
	_voice_noise 12, \base_midi_key, \pan, \period, \attack, \decay, \sustain, \release
	.endm

	.macro _voice_noise type:req, base_midi_key:req, pan:req, period:req, attack:req, decay:req, sustain:req, release:req
	.byte \type
	.byte \base_midi_key
	.if \pan != 0
	.byte (0x80 | \pan)
	.else
	.byte 0
	.endif
	.byte 0
	_voice_word (\period & 0x1)
	.byte (\attack  & 0x7)
	.byte (\decay   & 0x7)
	.byte (\sustain & 0xF)
	.byte (\release & 0x7)
	_voice_tail_padding
	.endm

	.macro voice_keysplit voice_group_pointer:req, keysplit_table_pointer:req
	.byte 0x40, 0, 0, 0
	_voice_word \voice_group_pointer
#ifdef PORTABLE_64BIT
	.8byte \keysplit_table_pointer
#else
	.int \keysplit_table_pointer
#endif
	.endm

	.macro voice_keysplit_all voice_group_pointer:req
	.byte 0x80, 0, 0, 0
	_voice_word \voice_group_pointer
#ifdef PORTABLE_64BIT
	.8byte 0
#else
	.int 0
#endif
	.endm

	.macro cry sample:req
	.byte 0x20, 60, 0, 0
	_voice_word \sample
	.byte 0xff, 0, 0xff, 0
	_voice_tail_padding
	.endm

	.macro cry_reverse sample:req
	.byte 0x30, 60, 0, 0
	_voice_word \sample
	.byte 0xff, 0, 0xff, 0
	_voice_tail_padding
	.endm
