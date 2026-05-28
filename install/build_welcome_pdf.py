"""
Build the Hans onboarding PDF.

Run from the cohost root:
    .venv\\Scripts\\python.exe install\\build_welcome_pdf.py

Produces: Cohost_Welcome_v1.0.pdf at the install root.
"""
from pathlib import Path
from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "Cohost_Welcome_v1.0.pdf"

ACCENT = (124, 92, 252)   # Aria purple
TEXT   = (30, 30, 36)
DIM    = (110, 110, 130)
RULE   = (210, 210, 220)


class Welcome(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*DIM)
        self.cell(0, 8, "Cohost - Aria | v1.0 Welcome Guide", align="L")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*DIM)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def h1(self, text):
        self.set_font("Helvetica", "B", 22)
        self.set_text_color(*ACCENT)
        self.cell(0, 12, text, ln=1)
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(6)

    def h2(self, text):
        self.ln(3)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*TEXT)
        self.cell(0, 8, text, ln=1)
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def h3(self, text):
        self.ln(1)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*TEXT)
        self.cell(0, 6, text, ln=1)

    def body(self, text):
        self.set_font("Helvetica", "", 11)
        self.set_text_color(*TEXT)
        self.multi_cell(0, 5.6, text)
        self.ln(2)

    def bullet(self, text):
        self.set_font("Helvetica", "", 11)
        self.set_text_color(*TEXT)
        # Indent + bullet character (use hyphen for max font compatibility)
        x_start = self.get_x()
        self.cell(6, 5.6, "-", ln=0)
        self.multi_cell(0, 5.6, text)
        self.set_x(x_start)

    def code(self, text):
        self.set_font("Courier", "", 10)
        self.set_fill_color(245, 245, 250)
        self.set_text_color(*TEXT)
        self.multi_cell(0, 5.4, text, fill=True, border=0)
        self.ln(2)

    def callout(self, title, text, color=ACCENT):
        x0 = self.l_margin
        y0 = self.get_y()
        usable_w = self.w - self.l_margin - self.r_margin
        # Title
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*color)
        self.set_x(x0 + 3)
        self.cell(usable_w - 3, 6, title, ln=1)
        # Body
        self.set_font("Helvetica", "", 10.5)
        self.set_text_color(*TEXT)
        self.set_x(x0 + 3)
        self.multi_cell(usable_w - 6, 5.4, text)
        y1 = self.get_y()
        # Left bar
        self.set_draw_color(*color)
        self.set_line_width(1.2)
        self.line(x0, y0, x0, y1)
        self.ln(3)


pdf = Welcome(orientation="P", unit="mm", format="A4")
pdf.set_auto_page_break(auto=True, margin=18)
pdf.set_margins(left=20, top=18, right=20)
pdf.add_page()

# ── Cover ─────────────────────────────────────────────────────────────────────
pdf.set_font("Helvetica", "B", 36)
pdf.set_text_color(*ACCENT)
pdf.ln(28)
pdf.cell(0, 14, "Cohost", ln=1, align="C")
pdf.set_font("Helvetica", "", 18)
pdf.set_text_color(*TEXT)
pdf.cell(0, 10, "Aria - your podcast co-host", ln=1, align="C")
pdf.ln(6)
pdf.set_font("Helvetica", "B", 14)
pdf.set_text_color(*ACCENT)
pdf.cell(0, 8, "Version 1.0", ln=1, align="C")
pdf.set_font("Helvetica", "", 12)
pdf.set_text_color(*DIM)
pdf.cell(0, 7, "Live tester edition - Hans (NVIDIA build)", ln=1, align="C")

pdf.ln(28)
pdf.set_font("Helvetica", "", 11)
pdf.set_text_color(*TEXT)
intro = (
    "Welcome, Hans. This is the first public build of Cohost. Aria is a podcast "
    "co-host that listens during your show and chimes in when you invite her. "
    "She is meant to be a second voice - she will not interrupt unless asked.\n\n"
    "You are the live NVIDIA tester for this version. If anything does not work "
    "the way you expect, anything is missing, or anything feels wrong - tell "
    "cypherstone. He will track every request and fix them. There is a feedback "
    "form on the last page of this guide, and a one-click 'Remote help' button "
    "in the app that lets him connect to your machine to diagnose problems."
)
pdf.multi_cell(0, 6.2, intro)

pdf.ln(6)
pdf.callout(
    "How to reach cypherstone",
    "Email: ralstonjeff1978@gmail.com\n"
    "In the app: click 'Remote help' in the sidebar - read him the URL and code.",
    color=ACCENT,
)

# ── Page 2: Install ───────────────────────────────────────────────────────────
pdf.add_page()
pdf.h1("Install")

pdf.h2("Prerequisites (one-time, ~5 min)")
pdf.body("Before running the installer, get these three things on your PC:")
pdf.bullet("Python 3.12 from https://www.python.org/downloads/release/python-3120/ "
           "- IMPORTANT: check 'Add python.exe to PATH' during install.")
pdf.bullet("Ollama for Windows from https://ollama.com/download/windows. After install, "
           "open PowerShell and run 'ollama signin' once to connect to Ollama Cloud. "
           "The $20/month plan unlocks the bigger brains; free tier works with limits.")
pdf.bullet("NVIDIA driver - up-to-date if you can play modern games. If Aria runs "
           "slow later, update from https://www.nvidia.com/Download/index.aspx.")

pdf.h2("Install (one-time, ~15 min)")
pdf.body("Once prerequisites are done:")
pdf.bullet("Make sure the Cohost folder has at least 15 GB free for downloads and "
           "model weights.")
pdf.bullet("Double-click INSTALL.bat. A window opens and shows progress. Do not close it.")
pdf.bullet("When you see 'Install complete' you are done with this step.")
pdf.bullet("If anything failed, email install\\install_log.txt back to cypherstone.")

pdf.h2("Self-test (one-time, ~2 min)")
pdf.body("This is the trust check before you record a real episode.")
pdf.bullet("Double-click SELFTEST.bat.")
pdf.bullet("It boots Aria, generates a test sentence, and lists your mics.")
pdf.bullet("Email install\\selftest_report.txt back to cypherstone.")
pdf.bullet("He will green-light it before your first episode.")

# ── Page 3: Run + Aria behavior ───────────────────────────────────────────────
pdf.add_page()
pdf.h1("Running Aria")

pdf.h2("Open the app")
pdf.body("Double-click CohostWeb.bat. Your browser opens to "
         "http://localhost:6500 (first free port in 6500-6510) with the visual "
         "interface. This is what you will use 99% of the time.")
pdf.body("There is also Cohost.bat for a terminal-only version. Same engine, "
         "no UI, slash commands instead of buttons.")

pdf.h2("How Aria behaves")
pdf.body("Aria is a co-host, not the host. She listens passively until invited.")
pdf.h3("Wake word")
pdf.body("Say 'Aria' or 'Hey Aria' during a recording. She opens a 90-second "
         "active window where she chimes in freely.")
pdf.h3("Hotkey")
pdf.body("Press Ctrl+Alt+A from anywhere - works even when the browser is not "
         "in focus. Same effect as the wake word.")
pdf.h3("Cooldown")
pdf.body("When the 90-second window closes, Aria enters a 180-second cooldown. "
         "During cooldown only a wake word reopens the window. This stops her "
         "from talking over you.")
pdf.h3("Free chime mode")
pdf.body("Sidebar toggle. When ON, Aria replies to every turn. Useful for solo "
         "recordings where you want a constant conversation partner.")
pdf.h3("Aria, chime in (button)")
pdf.body("Forces an immediate response from her without waiting for a wake word.")

pdf.h2("Sidebar controls")
pdf.bullet("Brain dropdown - top of sidebar. Grouped: 'Local (installed)' shows "
           "whatever you pulled with 'ollama pull'; 'Cloud' shows the curated "
           "list. Switch on the fly.")
pdf.bullet("Voice output toggle - mute Aria's voice but keep her text on screen.")
pdf.bullet("Mic selector - pick which microphone she listens on.")
pdf.bullet("Dream / Reflect - end-of-session reflection. Aria thinks about what "
           "went well and what she could do better. Improves her over time.")
pdf.bullet("Remote help - opens a 1-hour Cloudflare tunnel and shows you a "
           "URL plus a one-time code. Read both to cypherstone over the phone. "
           "Tunnel auto-closes after 1 hour or when you click Stop remote.")
pdf.bullet("End Episode - saves the session and closes Aria.")

# ── Page 4: CLI + Troubleshooting ─────────────────────────────────────────────
pdf.add_page()
pdf.h1("Reference")

pdf.h2("CLI slash commands (Cohost.bat only)")
pdf.code(
    "/brain          show brain menu, pick a different LLM\n"
    "/brain <name>   switch brain directly\n"
    "/voice          list voice options\n"
    "/voice <name>   switch voice\n"
    "/mic            list microphones\n"
    "/mic <number>   switch to a specific mic\n"
    "/whisper <size> change Whisper STT model (tiny|base|small|medium|large-v3)\n"
    "/guest <name>   set or change the guest\n"
    "/bio <text>     set guest bio\n"
    "/quote          save last guest line as a memorable quote\n"
    "/followup <text> flag a thread for follow-up\n"
    "/open           generate an episode opening\n"
    "/question       generate an interview question\n"
    "/status         show system status\n"
    "/memory         show memory stats\n"
    "/learning       show learning report\n"
    "/guests         list all past guests\n"
    "/episodes       list recent episodes\n"
    "/end            end and save current episode\n"
    "/help           full command list\n"
    "/quit           save and exit"
)

pdf.h2("Troubleshooting")
rows = [
    ("'Python 3.12 not detected'",
     "Install Python 3.12, check 'Add to PATH' during install, re-run INSTALL.bat."),
    ("'Ollama not found'",
     "Install from ollama.com/download/windows, then run 'ollama signin'."),
    ("'torch.cuda.is_available() is False' but you have NVIDIA",
     "Update NVIDIA driver, re-run INSTALL.bat."),
    ("Aria takes 30+ seconds to respond",
     "TTS fell back to CPU. Check selftest_report.txt - should say device = cuda. "
     "If not, update NVIDIA driver."),
    ("Mic not picking up",
     "Web UI: change mic in the sidebar dropdown. CLI: /mic then /mic <number>."),
    ("Aria never responds",
     "By default she is passive. Say 'Aria' or press Ctrl+Alt+A to invite her. "
     "Or toggle 'Free chime mode' in the sidebar."),
    ("Remote help button errors",
     "Install cloudflared: 'winget install Cloudflare.cloudflared' and try again."),
    ("Anything else",
     "Click 'Remote help' in the sidebar and send cypherstone the URL plus code."),
]
pdf.set_font("Helvetica", "B", 10)
pdf.set_fill_color(*ACCENT)
pdf.set_text_color(255, 255, 255)
col_w = (60, pdf.w - pdf.l_margin - pdf.r_margin - 60)
pdf.cell(col_w[0], 7, "Symptom", border=0, fill=True)
pdf.cell(col_w[1], 7, "Fix", border=0, fill=True, ln=1)
pdf.set_font("Helvetica", "", 10)
pdf.set_text_color(*TEXT)
fill = False
for sym, fix in rows:
    pdf.set_fill_color(248, 248, 252) if fill else pdf.set_fill_color(255, 255, 255)
    x0 = pdf.get_x()
    y0 = pdf.get_y()
    # Estimate heights
    pdf.multi_cell(col_w[0], 5.4, sym, border=0, fill=True)
    h1 = pdf.get_y() - y0
    pdf.set_xy(x0 + col_w[0], y0)
    pdf.multi_cell(col_w[1], 5.4, fix, border=0, fill=True)
    h2 = pdf.get_y() - y0
    h = max(h1, h2)
    pdf.set_y(y0 + h)
    fill = not fill

# ── Page 5: Feedback ──────────────────────────────────────────────────────────
pdf.add_page()
pdf.h1("This is v1.0 - your feedback shapes v1.1")

pdf.body(
    "You are the live NVIDIA tester for this build. Treat anything that "
    "surprises you as a bug report - cypherstone wants to hear it. "
    "Nothing is too small."
)

pdf.callout(
    "How to ask for changes",
    "There is no formal process. Email, text, call - whatever works. Use the "
    "template below if it helps, or just describe what you saw and what you "
    "wanted to happen. Every request gets tracked and triaged.",
    color=ACCENT,
)

pdf.h2("Feedback template (copy / paste into an email)")
pdf.code(
    "Date:\n"
    "Tester: Hans\n"
    "Build: Cohost v1.0\n\n"
    "Things that did not work\n"
    "  - [what happened, what you expected]\n"
    "  - [steps to reproduce if you can]\n\n"
    "Things I want added\n"
    "  - [feature, why you want it]\n\n"
    "Things I want changed or removed\n"
    "  - [what, why]\n\n"
    "How Aria sounded / felt during the test\n"
    "  - [too slow, too fast, awkward pauses, talked over you, etc.]\n\n"
    "Selftest result\n"
    "  - [device = cuda OR cpu, first_generate_secs, second_generate_secs]\n\n"
    "Anything else"
)

pdf.h2("Examples of useful feedback")
pdf.bullet("'When I say her name mid-sentence she sometimes responds before I "
           "finish. Can the wake-word be a full phrase like Aria-comma?'")
pdf.bullet("'180-second cooldown feels too long for a fast-paced segment. Make "
           "it configurable.'")
pdf.bullet("'Brain dropdown is too small to read - bigger font please.'")
pdf.bullet("'Want a button to save the last 30 seconds as a quote.'")

pdf.h2("Known limitations in v1.0")
pdf.bullet("Cloudflared (Remote help) is optional - installer tries winget but "
           "may need a manual install on some systems.")
pdf.bullet("Self-test does not yet verify the new wake-word and remote-help "
           "code paths - selftest_report.txt may pass even if those pieces are "
           "subtly broken. Report any weirdness anyway.")
pdf.bullet("Hotkey (Ctrl+Alt+A) registration is best-effort - on some Windows "
           "configurations it needs admin privileges. If the hotkey does not "
           "work, the wake word and the 'Aria, chime in' button still do.")

pdf.ln(6)
pdf.callout(
    "Bottom line",
    "If something does not work, ask. If something is missing, ask. If "
    "something is wrong, ask. cypherstone will work on every issue you raise.",
    color=ACCENT,
)

pdf.output(str(OUT))
print(f"Wrote: {OUT}")
