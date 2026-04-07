"""Parse a GEDCOM file and produce Mermaid family tree diagrams, split by branch."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


BRAZIL_STATE_ABBR = {
    "acre": "AC",
    "alagoas": "AL",
    "amapa": "AP",
    "amazonas": "AM",
    "bahia": "BA",
    "ceara": "CE",
    "distrito federal": "DF",
    "espirito santo": "ES",
    "goias": "GO",
    "maranhao": "MA",
    "mato grosso": "MT",
    "mato grosso do sul": "MS",
    "minas gerais": "MG",
    "para": "PA",
    "paraiba": "PB",
    "parana": "PR",
    "pernambuco": "PE",
    "piaui": "PI",
    "rio de janeiro": "RJ",
    "rio grande do norte": "RN",
    "rio grande do sul": "RS",
    "rondonia": "RO",
    "roraima": "RR",
    "santa catarina": "SC",
    "sao paulo": "SP",
    "sergipe": "SE",
    "tocantins": "TO",
}


# ── GEDCOM parser ────────────────────────────────────────────────────────────

def parse_ged(path: str) -> tuple[dict, dict]:
    individuals = {}
    families = {}
    current_id = None
    current_type = None
    current = {}

    def save():
        if current_id and current_type == "INDI":
            individuals[current_id] = dict(current)
        elif current_id and current_type == "FAM":
            families[current_id] = dict(current)

    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.rstrip()
            parts = line.split(" ", 2)
            if len(parts) < 2:
                continue
            level, tag = parts[0], parts[1]
            value = parts[2].strip() if len(parts) > 2 else ""

            if level == "0":
                save()
                current = {}
                current_id = None
                current_type = None
                if tag.startswith("@") and value:
                    current_id = tag
                    current_type = value
            elif level == "1":
                if tag in ("NAME", "SEX", "HUSB", "WIFE", "FAMC", "FAMS"):
                    if tag == "FAMS":
                        current.setdefault("FAMS", []).append(value)
                    else:
                        current[tag] = value
                elif tag == "CHIL":
                    current.setdefault("CHIL", []).append(value)
                elif tag == "BIRT":
                    current["_in_birt"] = True
                    current.pop("_in_deat", None)
                elif tag == "DEAT":
                    current["_in_deat"] = True
                    current.pop("_in_birt", None)
                else:
                    current.pop("_in_birt", None)
                    current.pop("_in_deat", None)
            elif level == "2":
                if tag == "DATE":
                    if current.get("_in_birt"):
                        current["BIRT_DATE"] = value
                    elif current.get("_in_deat"):
                        current["DEAT_DATE"] = value
                elif tag == "PLAC":
                    if current.get("_in_birt"):
                        current["BIRT_PLAC"] = format_place(value)
                    elif current.get("_in_deat"):
                        current["DEAT_PLAC"] = format_place(value)

    save()
    return individuals, families


def clean_name(name: str) -> str:
    return re.sub(r"/", "", name).strip()


def normalize_place_token(value: str) -> str:
    return (
        value.lower()
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("ã", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
        .strip()
    )


def format_place(place: str) -> str:
    parts = [part.strip() for part in place.split(",") if part.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return BRAZIL_STATE_ABBR.get(normalize_place_token(parts[0]), parts[0])

    city = parts[0]
    state = ""
    for token in parts[1:]:
        state = BRAZIL_STATE_ABBR.get(normalize_place_token(token), state)
    return f"{city}/{state}" if state else city


def ancestors_of(iid: str, individuals: dict, families: dict) -> set[str]:
    visited = set()
    queue = [iid]
    while queue:
        pid = queue.pop()
        if pid in visited:
            continue
        visited.add(pid)
        person = individuals.get(pid, {})
        famc = person.get("FAMC")
        if famc:
            fam = families.get(famc, {})
            for parent_key in ("HUSB", "WIFE"):
                parent = fam.get(parent_key)
                if parent and parent not in visited:
                    queue.append(parent)
    return visited


def descendants_of(iid: str, individuals: dict, families: dict) -> set[str]:
    visited = set()
    queue = [iid]
    while queue:
        pid = queue.pop()
        if pid in visited:
            continue
        visited.add(pid)
        person = individuals.get(pid, {})
        for fams_id in person.get("FAMS", []):
            fam = families.get(fams_id, {})
            for child in fam.get("CHIL", []):
                if child not in visited:
                    queue.append(child)
    return visited


def families_for_individuals(iids: set[str], families: dict) -> dict:
    result = {}
    for fid, fam in families.items():
        members = set()
        if fam.get("HUSB"):
            members.add(fam["HUSB"])
        if fam.get("WIFE"):
            members.add(fam["WIFE"])
        members.update(fam.get("CHIL", []))
        if members & iids:
            result[fid] = fam
    return result


# ── Mermaid rendering ────────────────────────────────────────────────────────

def mmd_id(raw: str) -> str:
    return raw.strip("@").replace("-", "_")


def make_mermaid(
    individuals: dict,
    families: dict,
    subset_iids: set[str],
    subset_fams: dict,
    output: str,
    title: str = "",
):
    lines = ["graph TD"]

    if title:
        lines.append(f'    _title["{title}"]')
        lines.append('    style _title fill:#ffffff,stroke:#ffffff,font-size:32px,font-weight:bold,color:#111111')
        lines.append("")

    lines += [
        "    classDef male fill:#D5E8D4,stroke:#1B5E20,color:#1B5E20,font-size:22px,font-weight:bold",
        "    classDef female fill:#FFE8CC,stroke:#7B3800,color:#7B3800,font-size:22px,font-weight:bold",
        "    classDef unknown fill:#E8E8E8,stroke:#444444,color:#222222,font-size:22px,font-weight:bold",
        "",
    ]

    for iid in sorted(subset_iids):
        data = individuals.get(iid, {})
        name = clean_name(data.get("NAME", "Unknown"))
        sex = data.get("SEX", "U")

        def year(date_str: str) -> str:
            m = re.search(r"\b(\d{4})\b", date_str)
            return m.group(1) if m else ""

        birt_year = year(data.get("BIRT_DATE", ""))
        deat_year = year(data.get("DEAT_DATE", ""))
        birt_plac = data.get("BIRT_PLAC", "")
        deat_plac = data.get("DEAT_PLAC", "")

        safe_name = name.replace('"', "'")
        label = safe_name
        birth_text = " ".join(filter(None, [birt_year, birt_plac]))
        death_text = " ".join(filter(None, [deat_year, deat_plac]))
        meta_lines = []
        if birth_text:
            meta_lines.append(f"b. {birth_text}")
        if death_text:
            meta_lines.append(f"d. {death_text}")

        nid = mmd_id(iid)
        css_class = {"M": "male", "F": "female"}.get(sex, "unknown")
        if meta_lines:
            label += "<br/>" + "<br/>".join(meta_lines)
        lines.append(f'    {nid}["{label}"]:::{css_class}')

    lines.append("")

    for fid, fam in subset_fams.items():
        husb_raw = fam.get("HUSB", "")
        wife_raw = fam.get("WIFE", "")
        parents = []
        if husb_raw and husb_raw in subset_iids:
            parents.append(mmd_id(husb_raw))
        if wife_raw and wife_raw in subset_iids:
            parents.append(mmd_id(wife_raw))
        for child_raw in fam.get("CHIL", []):
            if child_raw in subset_iids:
                for parent in parents:
                    lines.append(f"    {parent} --> {mmd_id(child_raw)}")

    lines.append("")
    Path(output).write_text("\n".join(lines), encoding="utf-8")


def find_mmdc() -> str | None:
    return shutil.which("mmdc")


def render(mmd_path: str, png_path: str):
    mmdc = find_mmdc()
    if not mmdc:
        print("  skipping render: mmdc not found (install @mermaid-js/mermaid-cli)")
        return

    cmd = [
        mmdc,
        "-i", mmd_path,
        "-o", png_path,
        "-w", "3200",
        "-H", "2400",
        "--backgroundColor", "white",
    ]

    puppeteer_cfg = Path(__file__).parent / ".puppeteerrc.json"
    if puppeteer_cfg.exists():
        cmd.extend(["-p", str(puppeteer_cfg)])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  mermaid error: {result.stderr.strip()}")
    else:
        size_kb = Path(png_path).stat().st_size // 1024
        print(f"  -> {png_path} ({size_kb}K)")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ged_path = sys.argv[1] if len(sys.argv) > 1 else "vault/family.ged"
    script_dir = Path(__file__).resolve().parent
    default_out = script_dir.parent / "img"
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else default_out
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Parsing {ged_path}...")
    individuals, families = parse_ged(ged_path)
    print(f"  {len(individuals)} individuals, {len(families)} families")

    proband_id = next(iter(individuals))
    proband = individuals[proband_id]
    print(f"  Proband: {clean_name(proband.get('NAME', '?'))}")

    famc_id = proband.get("FAMC")
    if not famc_id:
        print("No parent family found. Exporting full tree.")
        all_fams = families_for_individuals(set(individuals.keys()), families)
        make_mermaid(individuals, families, set(individuals.keys()), all_fams,
                     str(out_dir / "mermaid_tree.mmd"), "Full Family Tree")
        render(str(out_dir / "mermaid_tree.mmd"), str(out_dir / "mermaid_tree.png"))
        sys.exit(0)

    parent_fam = families[famc_id]
    father_id = parent_fam.get("HUSB")
    mother_id = parent_fam.get("WIFE")

    branches = []
    if father_id:
        branches.append((father_id, "", "paternal"))
    if mother_id:
        branches.append((mother_id, "", "maternal"))

    for root_id, title, label in branches:
        print(f"\nBuilding {label} branch...")
        iids = ancestors_of(root_id, individuals, families)
        iids.update(descendants_of(root_id, individuals, families))
        fams = families_for_individuals(iids, families)
        print(f"  {len(iids)} individuals, {len(fams)} families")

        mmd_path = str(out_dir / f"mermaid_tree_{label}.mmd")
        png_path = str(out_dir / f"mermaid_tree_{label}.png")
        make_mermaid(individuals, families, iids, fams, mmd_path, title)
        render(mmd_path, png_path)

    print("\nDone.")
