"""Complete inline US report coverage and integrity before SMTP."""
import io
import copy
import random
import tempfile
import unittest
from pathlib import Path
from PIL import Image,ImageDraw
from bs4 import BeautifulSoup
from src import report_inline,email_layout
from src.main import compose_email_message
from tools.preview_email import sample_data,make_stock

class InlineReportTests(unittest.TestCase):
    def test_all_218_rows_survive_and_any_missing_or_changed_segment_fails(self):
        data=sample_data()
        data["us"].extend(make_stock(f"EXTRA{i}",number=i) for i in range(5))
        data.update(kr=[],new_us=[],new_kr=[],etf_info={})
        source=email_layout.render_email(**data)
        expected=email_layout.inventory(source)
        self.assertEqual(len(expected["us"]),218)
        image=Image.new("RGB",(1360,4420),"white")
        draw=ImageDraw.Draw(image)
        rows=[]
        for index,ticker in enumerate(expected["us"]):
            top=40+index*20
            draw.rectangle((10,top+3,200+index,top+15),fill=(index%255,50,120))
            rows.append({"ticker":ticker,"top":top,"bottom":top+20})
        stream=io.BytesIO()
        image.save(stream,format="PNG")
        with tempfile.TemporaryDirectory() as directory:
            delivery,meta=report_inline.make_package(source,expected,stream.getvalue(),rows,{},directory)
            assets=report_inline.verify_package(source,delivery,expected,meta,directory)
            self.assertGreater(len(assets),1)
            self.assertLess(len(delivery.encode("utf-8")),report_inline.MAX_HTML_BYTES)
            self.assertEqual(meta["us_tickers"],expected["us"])
            self.assertFalse(BeautifulSoup(delivery,"html5lib").select("#us"))
            for change in ("omitted","reordered","changed"):
                altered=copy.deepcopy(meta)
                if change=="omitted":
                    altered["assets"]=altered["assets"][:-1]
                elif change=="reordered":
                    altered["assets"].reverse()
                else:
                    altered["assets"][0]["sha256"]="bad"
                with self.subTest(change=change),self.assertRaises(RuntimeError):
                    report_inline.verify_package(source,delivery,expected,altered,directory)
            with self.assertRaises(RuntimeError):
                report_inline.verify_package(source+"changed",delivery,expected,meta,directory)
    def test_images_are_display_content_with_no_attachment_filename(self):
        rng=random.Random(7)
        image=Image.frombytes("RGB",(600,200),rng.randbytes(600*200*3))
        stream=io.BytesIO()
        image.save(stream,format="PNG")
        png=stream.getvalue()
        html='<img src="cid:us-report-00" alt="미국 전체 표">'
        msg=compose_email_message(html,"test","a@example.test","b@example.test",{"us-report-00":png})
        self.assertGreater(len(msg.as_bytes()),95000)
        self.assertFalse(any(p.get_content_disposition()=="attachment" or p.get_filename() for p in msg.walk()))
        body=next(p for p in msg.walk() if p.get_content_type()=="text/html")
        self.assertEqual(body.get_payload(decode=True).decode("utf-8"),html)
        part=next(p for p in msg.walk() if p.get("Content-ID")=="<us-report-00>")
        self.assertEqual(part.get_payload(decode=True),png)
        self.assertEqual(part.get_content_disposition(),"inline")
    def test_large_text_body_is_rejected_even_when_transport_is_small(self):
        with self.assertRaisesRegex(RuntimeError,"never remove candidates"):
            compose_email_message("<p>"+"x"*31000+"</p>","test","a@example.test","b@example.test")

if __name__=="__main__":
    unittest.main()
