from pathlib import Path
import tempfile
import unittest
from deployment.stellaris_bilingual import alias, bilingual_value, rewrite, quote, build, read_localisations


class BilingualTests(unittest.TestCase):
    def test_references_do_not_reenter_bilingual_keys(self):
        en={'FLEET':'Fleet','DESC':'$FLEET|Y$ costs $VALUE$.'}
        rendered=rewrite(en['DESC'],en,'E')
        self.assertIn('$'+alias('FLEET','E')+'|Y$',rendered)
        self.assertIn('$VALUE$',rendered)
        self.assertNotIn('$FLEET|Y$',rendered)
        self.assertEqual(bilingual_value('FLEET',en,{'FLEET':'舰队'}),'$'+alias('FLEET','E')+'$（$'+alias('FLEET','C')+'$）')
    def test_fragments_remain_unchanged_and_long_text_uses_lines(self):
        self.assertIsNone(bilingual_value('X',{'X':'$VALUE$'},{'X':'$VALUE$单元'}))
        self.assertIn('\n',bilingual_value('X',{'X':'A description. '*10},{'X':'说明'}))
    def test_generation_bom_quoting_fonts_and_no_game_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);game=root/'game';docs=root/'documents';docs.mkdir()
            for lang in ('english','simp_chinese'):(game/'localisation'/lang).mkdir(parents=True)
            en=game/'localisation/english/source.yml';original='l_english:\n X:0 "Research"\n TEXT: "Say \\"hello\\".\\nKeep $VALUE|2$ energy."\n'
            en.write_text(original,encoding='utf-8-sig')
            (game/'localisation/simp_chinese/source.yml').write_text('l_simp_chinese:\n X: "研究"\n TEXT: "说你好。\\n保留$VALUE|2$能量。"\n',encoding='utf-8-sig')
            (game/'interface').mkdir();(game/'interface/fonts.gfx').write_text('languages = { "l_simp_chinese" }')
            (game/'launcher-settings.json').write_text('{"modsCompatibilityVersion":"4.5"}')
            out=docs/'mod/alex_bilingual_learning';report=build(game,docs,out,False)
            self.assertEqual(report['bilingual_entries'],2);self.assertTrue(report['requires_launcher_enable'])
            texts,counts,skipped=read_localisations(out);self.assertEqual(skipped,0);self.assertEqual(counts['english'],1)
            self.assertIn('研究',texts['english'][alias('X','C')])
            self.assertEqual(texts['english'][alias('TEXT','E')],'Say "hello".\nKeep $VALUE|2$ energy.')
            self.assertTrue((out/'localisation/replace/english/zz_alex_bilingual_l_english.yml').read_bytes().startswith(b'\xef\xbb\xbf'))
            self.assertEqual(en.read_text(encoding='utf-8-sig'),original)
            self.assertIn('"l_english"',(out/'interface/fonts.gfx').read_text(encoding='utf-8-sig'))


if __name__=='__main__':unittest.main()
