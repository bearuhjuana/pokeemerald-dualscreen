"""Compile actual data macros and decoder paths with both pointer layouts.

These host checks catch relocations and LP64 alignment failures independently
of the full game smoke test. Run with Python unittest discovery.
"""

from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(platform.machine() in ("x86_64", "AMD64") and
                     all(shutil.which(tool) for tool in
                         ("gcc", "g++", "nm", "objcopy", "readelf")),
                     "requires x86_64 GNU C/C++ and binutils")
class DataLayoutTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]
        self.temp = tempfile.TemporaryDirectory(prefix="android-data-layout-")
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def run_command(self, args):
        result = subprocess.run(args, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout


    def test_voice_layouts(self):
        root, out, run = self.root, self.out, self.run_command
        voice=(root/'asm/macros/music_voice.inc').read_text()
        # GNU ARM .align counts powers of two; GNU x86 .align counts bytes.
        groups=(root/'asm/macros/m4a.inc').read_text().replace(
            '\t.align 2', '\t.balign 4')
        fixture=r'''
        .section .data
        .byte 0
        voice_group demo
        voice0:
        voice_directsound 60,0,0x12345678,255,165,51,235
        voice1:
        voice_square_1 60,0,0,2,0,0,15,0
        voice2:
        voice_square_2 60,0,2,0,0,9,2
        voice3:
        voice_programmable_wave 60,0,0x23456789,0,7,15,1
        voice4:
        voice_noise 60,0,1,0,7,15,1
        voice5:
        voice_keysplit 0x3456789a,0x456789ab
        voice6:
        voice_keysplit_all 0x56789abc
        voice7:
        cry 0x6789abcd
        voice8:
        cry_reverse 0x789abcde
        voice9:
        voice_group sliced, 3
        '''
        for width in (32,64):
            src=out/f'voice{width}.S'
            src.write_text(groups+voice+fixture)
            flags=['-DPORTABLE_64BIT'] if width==64 else []
            obj=out/f'voice{width}.o'
            run(['gcc','-x','assembler-with-cpp',*flags,'-c',str(src),'-o',str(obj)])
            symbols={fields[2]:int(fields[0],16) for fields in
                     (line.split() for line in run(['nm',str(obj)]).splitlines())
                     if len(fields)==3}
            stride=24 if width==64 else 12
            self.assertEqual(symbols['voicegroup_demo'] % (width//8), 0)
            self.assertEqual(symbols['voicegroup_sliced'],
                             symbols['voice9'] - 3 * stride)
            self.assertTrue(all(symbols[f'voice{i+1}']-symbols[f'voice{i}']==stride for i in range(9)))
            run(['objcopy','--dump-section',f'.data={out}/voice{width}.bin',str(obj)])
            data=(out/f'voice{width}.bin').read_bytes()[symbols['voice0']:]
            ptr_offset=8 if width==64 else 4
            self.assertTrue(int.from_bytes(data[ptr_offset:ptr_offset+width//8],'little')==0x12345678)
            self.assertTrue(data[(16 if width==64 else 8):(20 if width==64 else 12)]==bytes([255,165,51,235]))
            self.assertTrue(int.from_bytes(data[5*stride+ptr_offset:5*stride+ptr_offset+width//8],'little')==0x3456789a)
            self.assertTrue(int.from_bytes(data[5*stride+(16 if width==64 else 8):6*stride],'little')==0x456789ab)
            if width==32:
                # Byte-for-byte legacy records for the fixture above.
                self.assertEqual(data, bytes.fromhex(
                    '003c000078563412ffa533eb'
                    '013c00000200000000000f00'
                    '023c00000200000000000902'
                    '033c00008967452300070f01'
                    '043c00000100000000070f01'
                    '400000009a785634ab896745'
                    '80000000bc9a785600000000'
                    '203c0000cdab8967ff00ff00'
                    '303c0000debc9a78ff00ff00'))

    def test_pointer_tables_link_as_shared_data(self):
        root, out, run = self.root, self.out, self.run_command
        macros=(root/'asm/macros/asm.inc').read_text()
        for name in ('battle_ai_scripts', 'battle_anim_scripts',
                     'battle_scripts_1', 'battle_scripts_2',
                     'contest_ai_scripts', 'event_scripts',
                     'field_effect_scripts', 'mystery_event_script_cmd_table'):
            with self.subTest(table=name):
                entries=[line for line in (root/'data'/(name+'.s')).read_text().splitlines()
                         if re.match(r'\s*(?:data_ptr|\.(?:int|4byte|word))\s', line)]
                src, obj = out/(name+'.S'), out/(name+'.o')
                src.write_text(macros+'\n.section .data\n'+'\n'.join(entries)+
                               '\n.section .note.GNU-stack,"",@progbits\n')
                run(['gcc', '-DPORTABLE_64BIT', '-x', 'assembler-with-cpp',
                     '-c', str(src), '-o', str(obj)])
                self.assertNotIn('R_X86_64_32', run(['readelf', '-r', str(obj)]))
                run(['gcc', '-shared', str(obj), '-o', str(out/(name+'.so'))])


    def test_generated_map_layouts(self):
        root, out, run = self.root, self.out, self.run_command
        map_driver=r'''
        #define main mapjson_main
        #include "MAPJSON_SOURCE"
        #undef main
        int main(int argc, char **argv) {
            version="emerald";
            string err;
            Json layouts=Json::parse(R"({"layouts_table_label":"gLayouts","layouts":[{"id":"1","name":"Layout","width":20,"height":30,"border_filepath":"OUTPUT_DIRECTORY/border.bin","blockdata_filepath":"OUTPUT_DIRECTORY/map.bin","primary_tileset":"Primary","secondary_tileset":"Secondary"}]})",err);
            Json map=Json::parse(R"({"name":"TestMap","layout":"1","music":3,"region_map_section":4,"requires_flash":false,"weather":5,"map_type":6,"allow_cycling":true,"allow_escaping":true,"allow_running":true,"show_map_name":true,"battle_scene":7,"connections":[{"direction":"down","offset":-2,"map":0}],"object_events":[],"warp_events":[],"coord_events":[],"bg_events":[]})",err);
            Json groups=Json::parse(R"({"group_order":["Group"],"Group":["TestMap","TestMap"]})",err);
            auto second_fields=map.object_items();
            second_fields["name"]="SecondMap";
            Json second_map(second_fields);
            std::cout << generate_layout_headers_text(layouts)
                      << generate_layouts_table_text(layouts)
                      << generate_map_header_text(map,layouts)
                      << generate_map_header_text(second_map,layouts)
                      << generate_map_connections_text(map)
                      << generate_groups_text(groups);
        }
        '''
        map_driver = map_driver.replace('MAPJSON_SOURCE', str(root / 'tools/mapjson/mapjson.cpp')).replace('OUTPUT_DIRECTORY', str(out))
        (out/'mapcheck.cpp').write_text(map_driver)
        (out/'border.bin').write_bytes(bytes(8))
        (out/'map.bin').write_bytes(bytes(20))
        run(['g++','-std=c++11',str(out/'mapcheck.cpp'),str(root/'tools/mapjson/json11.cpp'),'-o',str(out/'mapcheck')])
        generated=run([str(out/'mapcheck')])
        generated=re.sub(r'^@.*$', '',generated,flags=re.M)
        generated=generated.replace('::',':')
        macros=(root/'asm/macros/map.inc').read_text()+(root/'asm/macros/asm.inc').read_text()
        prefix=r'''
        #define TRUE 1
        #define FALSE 0
        #define NULL 0
        #define CONNECTION_SOUTH 1
        #define CONNECTION_NORTH 2
        #define CONNECTION_WEST 3
        #define CONNECTION_EAST 4
        #define CONNECTION_DIVE 5
        #define CONNECTION_EMERGE 6
        .section .data
        .balign 8
        Primary: .8byte 0
        Secondary: .8byte 0
        TestMap_MapEvents: .8byte 0
        TestMap_MapScripts: .8byte 0
        '''
        for width in (32,64):
            src=out/f'map{width}.S'
            src.write_text(prefix+macros+generated+'\n.section .note.GNU-stack,"",@progbits\n')
            obj=out/f'map{width}.o'
            flags=['-DPORTABLE_64BIT'] if width==64 else []
            run(['gcc','-x','assembler-with-cpp',*flags,'-c',str(src),'-o',str(obj)])
            symbols={fields[2]:int(fields[0],16) for fields in
                     (line.split() for line in run(['nm',str(obj)]).splitlines())
                     if len(fields)==3}
            ptr=width//8
            self.assertTrue(symbols['gLayouts']-symbols['Layout']==8+4*ptr)
            self.assertTrue(symbols['TestMap']%ptr==0)
            self.assertEqual(symbols['SecondMap']-symbols['TestMap'],
                             48 if width==64 else 28)
            self.assertTrue(symbols['TestMap_MapConnections']%ptr==0)
            self.assertTrue(symbols['Group']-symbols['TestMap_MapConnections']==(16 if width==64 else 8))
            self.assertTrue(symbols['gMapGroups']-symbols['Group']==2*ptr)
            reloc=run(['readelf','-r',str(obj)])
            self.assertTrue(('R_X86_64_64' if width==64 else 'R_X86_64_32') in reloc)
            if width==64: self.assertNotIn('R_X86_64_32', reloc)


    def test_field_effect_pointer_operands(self):
        root, out, run = self.root, self.out, self.run_command
        field=(root/'src/field_effect.c').read_text()
        start=field.index('uintptr_t FieldEffectScript_ReadWord(')
        end=field.index('void FieldEffectFreeGraphicsResources(',start)
        defs=r'''
        #include <stdint.h>
        #include <stdio.h>
        #include <string.h>
        #include <assert.h>
        typedef uint8_t u8;
        typedef uint16_t u16;
        typedef uint32_t u32;
        struct SpriteSheet { u16 tag; };
        struct SpritePalette { u16 tag; };
        static int sheets, palettes;
        u16 GetSpriteTileStartByTag(u16 tag){ assert(tag==42); return 0xFFFF; }
        void LoadSpriteSheet(struct SpriteSheet *sheet){ assert(sheet->tag==42); sheets++; }
        void LoadSpritePalette(struct SpritePalette *pal){ assert(pal->tag==43); palettes++; }
        u8 IndexOfSpritePaletteTag(u16 tag){ assert(tag==43); return 2; }
        void UpdateSpritePaletteWithWeather(u8 id){ assert(id==2); }
        u32 native(void){ return 123; }
        struct SpriteSheet sheet={42};
        struct SpritePalette pal={43};
        extern u8 field_script[];
        '''
        field_main=r'''
        int main(void) {
         u8 *p=field_script;
         u32 val=0;
         assert((uintptr_t)&sheet > UINT32_MAX);
         assert(*p++==5);
         FieldEffectScript_LoadTiles(&p);
         FieldEffectScript_LoadFadedPalette(&p);
         FieldEffectScript_CallNative(&p,&val);
         assert(val==123 && sheets==1 && palettes==1 && *p==4);
         printf("PASS field effects LP64 PIE: unaligned pointers above 4GB, native callback, 8-byte advancement\n");
        }
        '''
        (out/'fieldcheck.c').write_text(defs+field[start:end]+field_main)
        field_macros=(root/'asm/macros/asm.inc').read_text()+(root/'asm/macros/field_effect_script.inc').read_text()
        field_macros=re.sub(r'^@.*$', '',field_macros,flags=re.M)
        (out/'fieldcheck.S').write_text(field_macros+r'''
        .section .data
        .global field_script
        field_script:
        field_eff_loadgfx_callnative sheet,pal,native
        field_eff_end
        .section .note.GNU-stack,"",@progbits
        ''')
        run(['gcc','-DPORTABLE_64BIT','-fPIE','-pie',str(out/'fieldcheck.c'),str(out/'fieldcheck.S'),'-o',str(out/'fieldcheck')])
        run([str(out/'fieldcheck')])



if __name__ == "__main__":
    unittest.main()
