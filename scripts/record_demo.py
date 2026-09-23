#!/usr/bin/env python3
"""公開サイトを Playwright で操作しながら録画し、output/demo/JapanStatsMAPs_demo.mp4 を作る。

使い方: python3 scripts/record_demo.py [URL]
録画ではマウスが映らないため、カーソル位置を小さな円で示す。画面下に場面ごとの説明を重ねる。
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
URL = sys.argv[1] if len(sys.argv) > 1 else "https://shoei05.github.io/JapanStatsMAPs/"
OUT = ROOT / "output/demo"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1440, 900

OVERLAY = """
(() => {
  const st = document.createElement('style');
  st.textContent = `
    #demo-cursor{position:fixed;z-index:99999;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;
      background:rgba(197,72,123,.5);border:2px solid #1D4E5C;pointer-events:none;transition:transform .12s}
    #demo-cursor.down{transform:scale(.7)}
    #demo-cap{position:fixed;z-index:99998;left:50%;bottom:40px;transform:translateX(-50%);width:max-content;max-width:1380px;
      background:rgba(255,255,255,.97);color:#1F3036;border:2px solid #1D4E5C;padding:14px 32px;
      font:600 30px/1.45 "Zen Kaku Gothic New","Hiragino Sans",sans-serif;letter-spacing:.03em;text-align:center;
      box-shadow:0 4px 0 #EBCC2A;opacity:0;transition:opacity .35s}
    #demo-cap.on{opacity:1}`;
  document.head.append(st);
  const c = document.createElement('div'); c.id = 'demo-cursor'; document.body.append(c);
  const cap = document.createElement('div'); cap.id = 'demo-cap'; document.body.append(cap);
  addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => c.classList.add('down'), true);
  addEventListener('mouseup', () => c.classList.remove('down'), true);
  window.__cap = t => { cap.classList.remove('on'); setTimeout(() => { cap.textContent = t; if (t) cap.classList.add('on'); }, 250); };
})();
"""


def main():
    tmp = OUT / "_raw"
    shutil.rmtree(tmp, ignore_errors=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp),
                            record_video_size={"width": W, "height": H}, color_scheme="light")
        pg = ctx.new_page()
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_timeout(1500)  # 配置は表示前に計算しきる作りなので、読み込み後に少し待てば足りる
        pg.evaluate("fit()")
        pg.evaluate(OVERLAY)
        cap = lambda t: pg.evaluate("t => window.__cap(t)", t)  # noqa: E731
        m = pg.mouse
        m.move(W / 2, H / 2)

        def glide(x, y, steps=25):
            m.move(x, y, steps=steps)

        def click_el(sel, pause=0.6):
            loc = pg.locator(sel).first
            loc.scroll_into_view_if_needed()
            box = loc.bounding_box()
            glide(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            time.sleep(pause)
            m.down(); m.up()

        # 1. 全体
        time.sleep(2)
        cap("日本の公的統計を使った研究 1,248本を、65のテーマで地図にしました")
        time.sleep(4.5)
        cap("円はテーマ、線は論文で確認した「曝露 → アウトカム」の組合せです")
        time.sleep(4)

        # 2. 自殺・自傷の円を選ぶ
        pos = pg.evaluate("""() => { const n = sim.byId['suicide_selfharm']; const r = document.querySelector('#cv').getBoundingClientRect();
                                     return {x: r.left + n.x * sim.k + sim.tx, y: r.top + n.y * sim.k + sim.ty}; }""")
        cap("テーマを選ぶと、使われたデータ源と論文の一覧が右に出ます")
        glide(pos["x"], pos["y"], 40)
        time.sleep(0.8)
        m.down(); m.up()
        time.sleep(2.5)
        pg.evaluate("document.querySelector('#detail').scrollBy({top: 420, behavior: 'smooth'})")
        time.sleep(3.5)
        pg.evaluate("document.querySelector('#detail').scrollTo({top: 0}); scrollTo(0, 0)")

        # 3. 関連の行列
        cap("関連の行列：どの曝露とアウトカムの組合せが研究されているか")
        click_el('#tabs button[data-tab="matrix"]')
        time.sleep(2)
        pg.evaluate("document.querySelector('.matrix-scroll').scrollBy({top: 300, behavior: 'smooth'})")
        time.sleep(2.5)
        pg.evaluate("document.querySelector('.matrix-scroll').scrollBy({left: 500, behavior: 'smooth'})")
        time.sleep(2.5)
        pg.evaluate("scrollTo(0, 0)")

        # 4. データ源と年
        cap("データ源と年：各統計のどの年のデータが解析されてきたか")
        click_el('#tabs button[data-tab="survey"]')
        time.sleep(5)

        # 5. 論文一覧で検索
        cap("論文一覧：キーワード・データ源・データの年で絞り込めます")
        click_el('#tabs button[data-tab="list"]')
        time.sleep(1.5)
        click_el("#q")
        pg.keyboard.type("suicide", delay=140)
        time.sleep(1.2)
        pg.select_option("#paper-study", "人口動態統計")
        time.sleep(3.5)

        # 6. 論文のつながり
        cap("論文のつながり：参考文献やテーマが近い論文を並べます")
        click_el("#listpane .card .paper-details:nth-of-type(2)")
        time.sleep(7)
        cap("A 公開集計データ 794本・B 政府統計の個票 443本（27種類の公的統計から）")
        time.sleep(4)
        cap("")
        time.sleep(1)
        video = pg.video.path()
        ctx.close()
        b.close()
    mp4 = OUT / "JapanStatsMAPs_demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "20", "-preset", "slow", "-movflags", "+faststart", str(mp4)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(mp4)


if __name__ == "__main__":
    main()
