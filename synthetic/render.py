"""reportlab invoice renderer: 8 layouts driven by config dicts."""
import io
import datetime as dt
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit

PW, PH = 612, 792
FONTS = {"helv": ("Helvetica", "Helvetica-Bold"), "times": ("Times-Roman", "Times-Bold"), "cour": ("Courier", "Courier-Bold")}
BOTTOM = 62
TOT_H = 118
RIGHT_KEYS = {"parts", "hrs", "rate", "total", "amt", "unit", "price", "lump", "labtxt"}

LAB_STD = dict(inv="Invoice #", date="Date", unit="Unit #", vin="VIN", odo="Odometer", total="TOTAL DUE")

LAYOUTS = {
    "L1": dict(header="left", info="boxes", mode="combined_hrs", fs=8.5, thead="fill", grid=True, zebra=False, date_fmt="%m/%d/%Y",
               sym=True, commas=True, qtyfmt="int", vin=True, pn=True, qty=True, upper=False, footer="center",
               rows=[["inv", "date", "ro", "terms"], ["unit", "vin", "odo"]], lab=LAB_STD,
               cols=[("qty", "Qty", 32), ("pn", "Part #", 78), ("desc", "Description", 214), ("parts", "Parts", 56), ("hrs", "Hrs", 40), ("rate", "Rate", 50), ("total", "Line Total", 70)]),
    "L2": dict(header="center", info="kv", mode="separate_hrs", fs=8.5, thead="grey", grid=False, zebra=True, date_fmt="%b %d, %Y",
               sym=False, commas=True, qtyfmt="2dp", vin=True, pn=True, qty=True, upper=False, footer="right", sect=True,
               lab=dict(inv="Invoice No.", date="Invoice Date", unit="Equipment #", vin="VIN", odo="Mileage", total="Balance Due"),
               kv_left=["inv", "date", "po"], kv_right=["unit", "vin", "odo"],
               cols=[("qty", "Qty", 36), ("pn", "Part Number", 90), ("desc", "Description", 244), ("unit", "Unit Price", 80), ("amt", "Amount", 90)],
               cols2=[("desc", "Labor Description", 340), ("hrs", "Hours", 60), ("rate", "Rate", 70), ("amt", "Amount", 70)]),
    "L3": dict(header="right", info="boxes", mode="combined_lump", fs=9, thead="line", grid=False, zebra=False, date_fmt="%Y-%m-%d",
               sym=True, commas=True, qtyfmt="int", vin=True, pn=True, qty=True, upper=False, footer="left",
               rows=[["inv", "date", "po"], ["unit", "vin"], ["odo", "drv", "terms"]],
               lab=dict(inv="INVOICE NO", date="DATE", unit="UNIT", vin="VIN", odo="ODOMETER", total="TOTAL"),
               cols=[("qty", "Qty", 30), ("pn", "Part No.", 80), ("desc", "Description of Work", 226), ("parts", "Parts", 66), ("lump", "Labor", 66), ("total", "Total", 72)]),
    "L4": dict(header="mono", info="bar", mode="combined_hrs", fs=8.5, thead="dash", grid=False, zebra=False, date_fmt="%m/%d/%y",
               sym=False, commas=False, qtyfmt="int", vin=False, pn=False, qty=True, upper=True, footer="center",
               lab=dict(inv="INV#", date="DATE", unit="UNIT", vin="VIN", odo="ODO", total="TOTAL"),
               cols=[("qty", "QTY", 30), ("desc", "DESCRIPTION", 280), ("parts", "PARTS", 62), ("hrs", "HRS", 40), ("rate", "RATE", 56), ("total", "AMOUNT", 72)]),
    "L5": dict(header="banner", info="boxes", mode="separate_hrs", fs=8.5, thead="fill", grid=True, zebra=True, date_fmt="%d %b %Y",
               sym=True, commas=True, qtyfmt="int", vin=True, pn=True, qty=True, upper=False, footer="center",
               rows=[["inv", "date", "po", "ro"], ["unit", "vin", "odo"]],
               lab=dict(inv="Invoice", date="Date", unit="Unit", vin="VIN", odo="Odometer", total="Invoice Total"),
               cols=[("desc", "Description", 200), ("pn", "Part #", 80), ("qty", "Qty", 30), ("price", "Price", 60), ("hrs", "Hours", 40), ("rate", "Rate", 50), ("amt", "Amount", 80)]),
    "L6": dict(header="left", info="kv", mode="combined_text", fs=8.5, thead="line", grid=False, zebra=False, date_fmt="%m/%d/%Y",
               sym=True, commas=True, qtyfmt="int", vin=True, pn=True, qty=True, upper=False, footer="right",
               kv_left=["inv", "date", "drv"], kv_right=["unit", "vin", "odo"],
               lab=dict(inv="Invoice #", date="Date", unit="Truck/Trailer #", vin="VIN", odo="Odometer", total="Amount Due"),
               cols=[("qty", "Qty", 30), ("pn", "Part #", 78), ("desc", "Description", 200), ("parts", "Parts", 62), ("labtxt", "Labor (hrs @ rate)", 90), ("amt", "Amount", 80)]),
    "L7": dict(header="compact", info="bar", mode="combined_hrs", fs=9, thead="line", grid=False, zebra=False, date_fmt="%m/%d/%Y",
               sym=True, commas=True, qtyfmt="int", vin=False, pn=False, qty=False, upper=False, footer="center",
               lab=dict(inv="Invoice", date="Date", unit="Unit", vin="VIN", odo="Odometer", total="Total"),
               cols=[("desc", "Description of repair", 270), ("parts", "Parts", 70), ("hrs", "Labor hrs", 50), ("rate", "Rate", 70), ("total", "Total", 80)]),
    "L8": dict(header="center", info="boxes", mode="separate_lump", fs=9, thead="grey", grid=True, zebra=False, date_fmt="%B %d, %Y",
               sym=True, commas=True, qtyfmt="int", vin=True, pn=True, qty=True, upper=False, footer="center",
               rows=[["inv", "date", "po"], ["unit", "vin"], ["odo", "drv", "ro"]],
               lab=dict(inv="Invoice Number", date="Service Date", unit="Unit Number", vin="Vehicle ID (VIN)", odo="Odometer", total="TOTAL"),
               cols=[("qty", "Qty", 30), ("pn", "Part #", 86), ("desc", "Description", 270), ("unit", "Unit", 74), ("amt", "Amount", 80)]),
}
for _k, _v in LAYOUTS.items():
    _v["id"] = _k
    _v["hours"] = _v["mode"] in ("combined_hrs", "separate_hrs", "combined_text")


def layout_for(shop):
    L = dict(LAYOUTS[shop["layout"]])
    L["accent"] = shop["accent"]
    L["font"] = shop["font"] if L["id"] not in ("L4",) else "cour"
    return L


def money(v, L):
    s = f"{v:,.2f}" if L["commas"] else f"{v:.2f}"
    return ("$" + s) if L["sym"] else s


class R:
    def __init__(self, c, inv, npages, hw, cap, marks):
        self.c, self.inv, self.L = c, inv, inv["L"]
        self.shop = inv["shop"]
        self.npages, self.hw, self.cap, self.marks = npages, hw or set(), cap, marks
        self.page = 1
        self.rows_on_page = 0
        self.acc = self.L["accent"]

    # -- primitives
    def font(self, bold=False):
        return FONTS[self.L["font"]][1 if bold else 0]

    def t(self, x, y, s, size=9, bold=False, align="l", color=(0, 0, 0)):
        c = self.c
        c.setFillColorRGB(*color)
        c.setFont(self.font(bold), size)
        if align == "l":
            c.drawString(x, y, s)
        elif align == "r":
            c.drawRightString(x, y, s)
        else:
            c.drawCentredString(x, y, s)

    def val(self, name, text, x, y, size, bold=True, align="l", w=70):
        """Value that may be handwritten instead of printed."""
        if name in self.hw:
            self.marks.append(dict(page=self.page, text=text, x=x, y=y, align=align, size=size, name=name))
            self.c.setStrokeColorRGB(.55, .55, .55)
            self.c.setLineWidth(.4)
            x0 = x if align == "l" else x - w
            self.c.line(x0, y - 2, x0 + w, y - 2)
        else:
            self.t(x, y, text, size, bold, align)

    def logo(self, x, y, s=44):
        c = self.c
        c.setFillColorRGB(*self.acc)
        c.rect(x, y, s, s, fill=1, stroke=0)
        ini = "".join(w[0] for w in self.shop["name"].replace("&", "").split()[:2]).upper()
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", s * .42)
        c.drawCentredString(x + s / 2, y + s * .33, ini)
        c.setFillColorRGB(1, 1, 1)
        c.rect(x, y + s * .14, s, 2, fill=1, stroke=0)

    # -- header
    def header(self):
        L, sh, c, h = self.L, self.shop, self.c, self.L["header"]
        name = sh["name"].upper() if L["upper"] else sh["name"]
        c.setStrokeColorRGB(*self.acc)
        if h == "left":
            self.logo(36, 726)
            self.t(90, 750, name, 17, True, color=self.acc)
            self.t(90, 737, sh["addr"], 8.5)
            self.t(90, 726, "Phone " + sh["phone"], 8.5)
            self.t(576, 750, "INVOICE", 22, True, "r", self.acc)
            c.setLineWidth(1.5)
            c.line(36, 716, 576, 716)
            return 702
        if h == "center":
            self.t(306, 762, name, 20, True, "c", self.acc)
            self.t(306, 749, sh["addr"], 9, False, "c")
            self.t(306, 738, "Tel: " + sh["phone"], 9, False, "c")
            c.setLineWidth(2)
            c.line(36, 730, 576, 730)
            self.t(36, 714, "REPAIR INVOICE" if L["id"] == "L2" else "SERVICE INVOICE", 11, True)
            return 704
        if h == "right":
            self.logo(528, 728, 48)
            self.t(516, 756, name, 18, True, "r", self.acc)
            self.t(516, 743, sh["addr"], 8.5, False, "r")
            self.t(516, 732, sh["phone"], 8.5, False, "r")
            self.t(36, 752, "Repair Invoice", 20, False, color=(.45, .45, .45))
            return 706
        if h == "banner":
            c.setFillColorRGB(*self.acc)
            c.rect(0, 716, PW, 76, fill=1, stroke=0)
            self.t(36, 764, name, 21, True, color=(1, 1, 1))
            self.t(36, 748, sh["addr"] + "  |  " + sh["phone"], 9, color=(1, 1, 1))
            self.t(576, 764, "INVOICE", 20, True, "r", (1, 1, 1))
            return 700
        if h == "mono":
            self.t(36, 760, name, 14, True)
            self.t(36, 747, sh["addr"].upper(), 9)
            self.t(36, 736, "TEL " + sh["phone"], 9)
            self.t(576, 760, "*** INVOICE ***", 12, True, "r")
            self.t(36, 722, "-" * 88, 9)
            return 708
        if h == "compact":
            self.t(36, 760, name, 13, True)
            self.t(36, 749, sh["addr"] + "  -  " + sh["phone"], 8)
            self.t(576, 760, "Invoice", 14, False, "r")
            c.setLineWidth(.6)
            c.setStrokeColorRGB(0, 0, 0)
            c.line(36, 741, 576, 741)
            return 730

    def cont_header(self):
        c = self.c
        self.t(36, 764, self.shop["name"], 11, True, color=self.acc)
        self.t(576, 764, f'Invoice {self.inv["header"]["invoice_number"]} (continued)', 10, False, "r")
        c.setStrokeColorRGB(*self.acc)
        c.setLineWidth(1)
        c.line(36, 756, 576, 756)
        return 744

    # -- info block
    def info_values(self):
        inv, L = self.inv, self.L
        h = inv["header"]
        v = dict(inv=h["invoice_number"], date=dt.date.fromisoformat(h["invoice_date"]).strftime(L["date_fmt"]),
                 unit=h["unit_number"], po=inv["extra"]["po"], ro=inv["extra"]["ro"], drv=inv["extra"]["drv"],
                 terms=inv["extra"]["terms"])
        if h["vin"]:
            v["vin"] = h["vin"]
        if h["odometer"] is not None:
            v["odo"] = f'{h["odometer"]:,}' if L["commas"] else str(h["odometer"])
        return v

    def lab(self, k):
        L = self.L
        d = dict(po="PO #", ro="RO #", drv="Driver", terms="Terms")
        s = L["lab"].get(k) or d[k]
        return s

    def info(self, y):
        L, c = self.L, self.c
        v = self.info_values()
        st = L["info"]
        # bill-to
        if st in ("boxes", "kv"):
            self.t(36, y, "BILL TO", 7, True, color=(.4, .4, .4))
            self.t(36, y - 10, "Redline Carriers, Inc.", 9, True)
            self.t(36, y - 20, "6100 Logistics Pkwy, Fort Worth, TX 76177", 8)
            y -= 30
        if st == "boxes":
            for row in L["rows"]:
                names = [n for n in row if n in v]
                wts = [2.4 if n == "vin" else 1 for n in names]
                tot = sum(wts)
                x = 36
                bh = 30
                for n, wt in zip(names, wts):
                    w = 540 * wt / tot
                    c.setStrokeColorRGB(.6, .6, .6)
                    c.setLineWidth(.6)
                    c.rect(x, y - bh, w, bh, stroke=1, fill=0)
                    self.t(x + 4, y - 9, self.lab(n), 6.5, False, color=(.4, .4, .4))
                    isvin = n == "vin"
                    self.val(n if n in ("unit", "odo") else "-", v[n], x + 5, y - 24, 10 if not isvin else 9.5, True, w=w - 12)
                    x += w
                y -= bh + 0
            return y - 14
        if st == "kv":
            yy = y - 4
            for col, names in ((36, L["kv_left"]), (330, L["kv_right"])):
                y2 = yy
                for n in names:
                    if n not in v:
                        continue
                    self.t(col, y2, self.lab(n) + ":", 8.5, False, color=(.3, .3, .3))
                    self.val(n if n in ("unit", "odo") else "-", v[n], col + 80, y2, 9.5, True, w=110)
                    y2 -= 13
            return yy - 13 * 3 - 8
        if st == "bar":
            yy = y
            order = [n for n in ("inv", "date", "unit", "vin", "odo") if n in v]
            x = 36
            for n in order:
                lab = self.lab(n) + ": "
                self.t(x, yy, lab, 8.5, False)
                x += self.c.stringWidth(lab, self.font(False), 8.5) + 1
                s = v[n].upper() if L["upper"] else v[n]
                self.val(n if n in ("unit", "odo") else "-", s, x, yy, 9.5, True, w=70)
                x += max(self.c.stringWidth(s, self.font(True), 9.5), 60 if n in ("unit", "odo") and self.hw else 0) + 16
            self.t(36, yy - 16, "BILL TO: Redline Carriers, Inc.  6100 Logistics Pkwy, Fort Worth, TX 76177"[:90], 8)
            self.t(36, yy - 28, f'PO {self.inv["extra"]["po"]}   Terms {self.inv["extra"]["terms"]}   Driver {v["drv"]}', 8)
            return yy - 46

    # -- table
    def cell(self, k, ln):
        L = self.L
        if k == "qty":
            if ln["qty"] is None:
                return ""
            return f'{ln["qty"]:.0f}' if L["qtyfmt"] == "int" else f'{ln["qty"]:.2f}'
        if k == "pn":
            return ln["part_number"] or ""
        if k == "desc":
            return ln["description"]
        if k == "parts":
            return money(ln["parts_price"], L) if ln["parts_price"] is not None else ""
        if k == "hrs":
            return f'{ln["labour_hours"]:.1f}' if ln["labour_hours"] is not None else ""
        if k == "rate":
            return money(ln["labour_rate"], L) if ln["labour_rate"] is not None else ""
        if k == "labtxt":
            return f'{ln["labour_hours"]:.1f} @ {ln["labour_rate"]:.2f}' if ln["labour_hours"] is not None else ""
        if k == "lump":
            return money(ln["lump"], L) if ln.get("lump") is not None else ""
        if k in ("total", "amt"):
            return money(ln["line_total"], L)
        if k in ("unit", "price"):
            return money(ln["unit_price"], L) if ln.get("unit_price") is not None else ""
        return ""

    def colhdr(self, y, cols):
        L, c = self.L, self.c
        x0 = 36
        hh = 16
        th = L["thead"]
        if th in ("fill", "grey"):
            c.setFillColorRGB(*(self.acc if th == "fill" else (.86, .86, .86)))
            c.rect(x0, y - hh, 540, hh, fill=1, stroke=0)
        col = (1, 1, 1) if th == "fill" else (0, 0, 0)
        x = x0
        for k, title, w in cols:
            if k in RIGHT_KEYS:
                self.t(x + w - 3, y - 11, title, L["fs"] - .5, True, "r", col)
            elif k == "qty":
                self.t(x + w / 2, y - 11, title, L["fs"] - .5, True, "c", col)
            else:
                self.t(x + 3, y - 11, title, L["fs"] - .5, True, "l", col)
            x += w
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(.8)
        if th == "line":
            c.line(x0, y - hh, x0 + 540, y - hh)
        if th == "dash":
            self.t(x0, y - hh - 1, "-" * 88, 9)
        return y - hh - (4 if th == "dash" else 0)

    def draw_table(self, y, cols, lines, last):
        L, c = self.L, self.c
        fs = L["fs"]
        lead = fs + 2.6
        y = self.colhdr(y, cols)
        for i, ln in enumerate(lines):
            cells = []
            nl = 1
            for k, title, w in cols:
                s = self.cell(k, ln)
                if k == "desc":
                    parts = simpleSplit(s, self.font(False), fs, w - 8) or [""]
                    nl = max(nl, len(parts))
                    cells.append(parts)
                else:
                    cells.append(s)
            rh = nl * lead + 5
            bottom = BOTTOM + (TOT_H if (last and i == len(lines) - 1) else 0)
            if y - rh < bottom or (self.cap and self.page == 1 and self.rows_on_page >= self.cap):
                y = self.newpage()
                y = self.colhdr(y, cols)
            if L["zebra"] and i % 2 == 1:
                c.setFillColorRGB(.94, .94, .94)
                c.rect(36, y - rh, 540, rh, fill=1, stroke=0)
            x = 36
            base = y - 4 - fs * .85
            for (k, title, w), s in zip(cols, cells):
                if k == "desc":
                    for j, p in enumerate(s):
                        self.t(x + 4, base - j * lead, p, fs)
                elif k == "hrs" and "hrs" in self.hw and s:
                    self.marks.append(dict(page=self.page, text=s, x=x + w - 4, y=base, align="r", size=fs, name="hrs"))
                elif k in RIGHT_KEYS:
                    self.t(x + w - 3, base, s, fs, False, "r")
                elif k == "qty":
                    self.t(x + w / 2, base, s, fs, False, "c")
                else:
                    self.t(x + 3, base, s, fs)
                x += w
            c.setStrokeColorRGB(.7, .7, .7)
            c.setLineWidth(.4)
            if L["grid"]:
                c.rect(36, y - rh, 540, rh, fill=0, stroke=1)
                x = 36
                for k, title, w in cols[:-1]:
                    x += w
                    c.line(x, y, x, y - rh)
            elif L["thead"] != "dash":
                c.line(36, y - rh, 576, y - rh)
            y -= rh
            self.rows_on_page += 1
        return y - 8

    # -- totals / footer / pages
    def totals(self, y):
        L, c, h = self.L, self.c, self.inv["header"]
        x, w = 360, 216
        y -= 6
        self.t(36, y - 8, "Parts and labor warranted per shop policy. Payment due per terms." if not L["upper"] else "PARTS & LABOR WARRANTED PER SHOP POLICY.", 7.5, color=(.35, .35, .35))
        self.t(36, y - 40, "Authorized by: ______________________", 8)
        for i, (lab, v) in enumerate((("Subtotal", h["subtotal"]), (self.inv["tax_label"], h["tax"]))):
            self.t(x + 6, y - 10 - i * 15, lab, 9)
            self.t(x + w - 6, y - 10 - i * 15, money(v, L), 9.5, False, "r")
        y2 = y - 52
        c.setStrokeColorRGB(*self.acc)
        c.setLineWidth(1.2)
        c.rect(x, y2 - 6, w, 24, stroke=1, fill=0)
        self.t(x + 6, y2 + 3, L["lab"]["total"], 10, True)
        s = money(h["total"], L)
        self.val("total", s, x + w - 6, y2 + 3, 11.5, True, "r", w=96)

    def footer(self):
        L, s = self.L, f"Page {self.page} of {self.npages}"
        f = L["footer"]
        c = self.c
        c.setStrokeColorRGB(.7, .7, .7)
        if f == "center":
            self.t(306, 38, s, 8, False, "c", (.3, .3, .3))
        elif f == "right":
            self.t(576, 38, s, 8, False, "r", (.3, .3, .3))
        else:
            self.t(36, 38, f'{self.shop["name"]} - Invoice {self.inv["header"]["invoice_number"]}    {s}', 7.5, False, "l", (.3, .3, .3))

    def newpage(self):
        self.footer()
        self.c.showPage()
        self.page += 1
        self.rows_on_page = 0
        return self.cont_header()

    def run(self):
        y = self.header()
        y = self.info(y)
        lines = self.inv["lines"]
        L = self.L
        if L.get("sect"):
            parts = [l for l in lines if l["kind"] == "parts"]
            lab = [l for l in lines if l["kind"] != "parts"]
            if parts:
                y = self.draw_table(y, L["cols"], parts, False)
            if lab:
                y = self.draw_table(y, L["cols2"], lab, True)
        else:
            y = self.draw_table(y, L["cols"], lines, True)
        self.totals(y)
        self.footer()
        self.c.showPage()


def draw_invoice(c, inv, npages, hw=None, cap=None, marks=None):
    r = R(c, inv, npages, hw, cap, marks if marks is not None else [])
    r.run()
    return r.page


def count_pages(inv, cap=None):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PW, PH), invariant=1)
    return draw_invoice(c, inv, 1, None, cap)


def make_pdf(path_or_buf, invs, hw_list=None, caps=None):
    """invs: list of inv dicts. returns (pages per invoice, marks per invoice)"""
    c = canvas.Canvas(path_or_buf, pagesize=(PW, PH), invariant=1)
    c.setTitle("Invoice")
    pages, allmarks = [], []
    for i, inv in enumerate(invs):
        cap = caps[i] if caps else None
        n = count_pages(inv, cap)
        marks = []
        draw_invoice(c, inv, n, (hw_list[i] if hw_list else None), cap, marks)
        pages.append(n)
        allmarks.append(marks)
    c.save()
    return pages, allmarks
