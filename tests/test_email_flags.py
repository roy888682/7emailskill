import base64
import io
import re
import unittest
from PIL import Image
from src.email_flags import flag_html, flag_images, inline_flag_sources

def component_count(image, bounds, predicate):
    left, top, right, bottom = bounds
    pending = {(x,y) for y in range(top,bottom) for x in range(left,right) if predicate(image.getpixel((x,y)))}
    count = 0
    while pending:
        count += 1
        stack = [pending.pop()]
        while stack:
            x,y = stack.pop()
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    neighbor = (x+dx,y+dy)
                    if neighbor in pending:
                        pending.remove(neighbor)
                        stack.append(neighbor)
    return count

class FlagTests(unittest.TestCase):
    def setUp(self):
        self.pngs = flag_images()
        self.images = {c:Image.open(io.BytesIO(png)).convert("RGB") for c,png in self.pngs.items()}

    def test_png_dimensions_and_signature(self):
        self.assertEqual(self.images["us"].size,(152,80))
        self.assertEqual(self.images["kr"].size,(120,80))
        for png in self.pngs.values():
            self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_us_thirteen_stripes_and_fifty_stars(self):
        image = self.images["us"]
        for stripe in range(13):
            pixel = image.getpixel((140,int((stripe+.5)*80/13)))
            target = (178,34,52) if stripe%2==0 else (255,255,255)
            self.assertTrue(all(abs(a-b)<=3 for a,b in zip(pixel,target)))
        self.assertEqual(component_count(image,(0,0,60,42),lambda rgb:min(rgb)>=210),50)

    def test_kr_taegeuk_and_four_trigrams(self):
        image = self.images["kr"]
        self.assertEqual(image.getpixel((2,2)),(255,255,255))
        self.assertEqual(image.getpixel((60,28)),(205,46,58))
        self.assertEqual(image.getpixel((60,52)),(0,71,160))
        for bounds,count in [((0,0,60,40),3),((60,0,120,40),5),((0,40,60,80),4),((60,40,120,80),6)]:
            self.assertEqual(component_count(image,bounds,lambda rgb:max(rgb)<60),count)

    def test_country_cids_are_images_without_emoji(self):
        for country in ("US","USD"):
            self.assertIn('cid:u',flag_html(country))
        for country in ("KR","KRW","KOSPI","KOSDAQ"):
            self.assertIn('cid:k',flag_html(country))
        source=flag_html("US")+flag_html("KR")
        self.assertNotIn("🇺🇸",source)
        self.assertNotIn("🇰🇷",source)
        self.assertIn('alt="성조기"',source)
        self.assertIn('alt="태극기"',source)

    def test_standalone_html_embeds_pngs_and_is_idempotent(self):
        source=flag_html("US")+flag_html("KR")
        preview=inline_flag_sources(source)
        encoded=re.findall(r'src="data:image/png;base64,([^"]+)"',preview)
        self.assertEqual([base64.b64decode(x) for x in encoded],[self.pngs["us"],self.pngs["kr"]])
        self.assertNotIn("cid:",preview)
        self.assertEqual(inline_flag_sources(preview),preview)
        self.assertIn("data:image/png;base64,",inline_flag_sources("<img src='cid:k'>"))

    def test_unquoted_compact_cids_preserve_exact_pngs(self):
        source = '<img src=cid:u><img src=cid:k>'
        preview = inline_flag_sources(source)
        encoded = re.findall(r'src="data:image/png;base64,([^"]+)"',preview)
        self.assertEqual([base64.b64decode(x) for x in encoded],[self.pngs["us"],self.pngs["kr"]])
        self.assertNotIn("cid:", preview)

    def test_cached_assets(self):
        self.assertIs(flag_images()["us"],self.pngs["us"])
        self.assertIs(flag_images()["kr"],self.pngs["kr"])

if __name__ == "__main__":
    unittest.main()
