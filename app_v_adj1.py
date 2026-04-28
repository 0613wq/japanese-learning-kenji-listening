# ═══════════════════════════════════════════════════
# 日语变形词汇听力练习  v2.0
# Streamlit + Google Gemini + edge_tts + GitHub Gist
# ═══════════════════════════════════════════════════
import streamlit as st
import edge_tts
import asyncio, io, random, datetime, json, requests, time, time

st.set_page_config(
    page_title="日语变形听力", page_icon="🇯🇵",
    layout="centered", initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  .word-box {
      text-align:center; font-size:58px; font-weight:700;
      letter-spacing:4px; padding:18px 0 12px; min-height:96px; line-height:1.1;
  }
  .word-box.hidden { filter:blur(14px); user-select:none; }
  .form-tag {
      display:inline-block; padding:3px 12px; border-radius:20px;
      background:#e8f4fd; color:#1a6fa8; font-size:13px; font-weight:600;
      margin-bottom:6px;
  }
  .meaning-row {
      border-left:3px solid #5ba4d4; padding:6px 10px;
      margin:5px 0; font-size:14px; background:#f7fbff; border-radius:0 6px 6px 0;
  }
  div.stButton > button { border-radius:10px; }
  audio { width:100% !important; }
</style>
""", unsafe_allow_html=True)

# ─── 语音 & 速度 ──────────────────────────────────
VOICES = {
    "🎀 七海 Nanami（女）": "ja-JP-NanamiNeural",
    "🎵 圭太 Keita（男）":  "ja-JP-KeitaNeural",
}
SPEEDS = {
    "🐢 0.75×": "-25%", "🐇 0.9×": "-10%",
    "▶ 1.0×":  "+0%",  "⚡ 1.15×": "+15%", "🚀 1.3×": "+30%",
}

# ─── 变形类型配置 ─────────────────────────────────
# weight 影响随机抽到的概率（3=主要，1=次要）
VERB_FORMS = [
    {"id":"te",        "label":"て形",     "weight":3},
    {"id":"past",      "label":"た形",     "weight":3},
    {"id":"nai",       "label":"ない形",   "weight":3},
    {"id":"masu",      "label":"ます形",   "weight":3},
    {"id":"potential", "label":"可能形",   "weight":1},
    {"id":"passive",   "label":"被動形",   "weight":1},
    {"id":"causative", "label":"使役形",   "weight":1},
    {"id":"ba",        "label":"ば条件形", "weight":1},
]
ADJ_FORMS = [
    {"id":"adj_neg",  "label":"否定形",   "weight":2},
    {"id":"adj_past", "label":"過去形",   "weight":2},
    {"id":"adj_adv",  "label":"副詞形",   "weight":1},
    {"id":"adj_te",   "label":"て形連接", "weight":1},
]
ALL_FORMS = VERB_FORMS + ADJ_FORMS

# 判断词类所属（宽松匹配，兼容中日文标注）
VERB_TYPE_KEYS = {"一段", "五段", "カ変", "サ変", "动词"}
ADJ_TYPE_KEYS  = {"い形", "な形", "形容"}

GIST_FILENAME = "japanese_inflection_words.csv"


# ═══════════════════════════════════════════════════
# GitHub Gist 工具
# ═══════════════════════════════════════════════════
def _gist_cfg():
    try:
        token   = st.secrets["github"]["token"]
        gist_id = st.secrets["github"].get("gist_id", "")
        return token, gist_id or None
    except Exception:
        return None, None

def _gist_enabled():
    return bool(_gist_cfg()[0])

def _gist_headers():
    token, _ = _gist_cfg()
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

def _gist_find():
    page = 1
    while True:
        r = requests.get("https://api.github.com/gists", headers=_gist_headers(),
                         params={"per_page": 100, "page": page}, timeout=10)
        r.raise_for_status()
        items = r.json()
        if not items:
            return None
        for item in items:
            if GIST_FILENAME in item.get("files", {}):
                return item["id"]
        page += 1

def _gist_load_raw(gist_id):
    r = requests.get(f"https://api.github.com/gists/{gist_id}",
                     headers=_gist_headers(), timeout=10)
    r.raise_for_status()
    raw_url = r.json()["files"][GIST_FILENAME]["raw_url"]
    return requests.get(raw_url, timeout=10).text

def _gist_save_raw(csv_text, gist_id=None):
    payload = {"description": "日语变形词汇听力练习 — 词库备份",
               "files": {GIST_FILENAME: {"content": csv_text}}}
    if gist_id:
        r = requests.patch(f"https://api.github.com/gists/{gist_id}",
                           headers=_gist_headers(), json=payload, timeout=10)
    else:
        payload["public"] = False
        r = requests.post("https://api.github.com/gists",
                          headers=_gist_headers(), json=payload, timeout=10)
    r.raise_for_status()
    return r.json()["id"]

def do_gist_load():
    token, gist_id = _gist_cfg()
    if not token:
        st.error("❌ 未配置 GitHub Token（secrets.toml → [github] token）"); return
    with st.spinner("☁️ 从 GitHub Gist 加载…"):
        try:
            if not gist_id:
                gist_id = _gist_find()
                if not gist_id:
                    st.warning(f"⚠️ 未找到 `{GIST_FILENAME}`，请先保存一次"); return
            csv_text = _gist_load_raw(gist_id)
        except Exception as e:
            st.error(f"❌ 加载失败：{e}"); return
    n = st.session_state.store.import_csv(csv_text)
    st.session_state.gist_id        = gist_id
    st.session_state.gist_last_sync = datetime.datetime.now().strftime("%H:%M:%S")
    st.success(f"✅ 已加载 {n} 个新词" if n else "✅ 词库已是最新")
    st.rerun()

def do_gist_save():
    token, cfg_id = _gist_cfg()
    if not token:
        st.error("❌ 未配置 GitHub Token"); return
    store = st.session_state.store
    if not store.words:
        st.warning("⚠️ 词库为空"); return
    gist_id = st.session_state.get("gist_id") or cfg_id
    with st.spinner("☁️ 保存到 GitHub Gist…"):
        try:
            if not gist_id:
                gist_id = _gist_find()
            new_id = _gist_save_raw(store.export_csv(), gist_id)
        except Exception as e:
            st.error(f"❌ 保存失败：{e}"); return
    st.session_state.gist_id        = new_id
    st.session_state.gist_last_sync = datetime.datetime.now().strftime("%H:%M:%S")
    if not gist_id:
        st.success("✅ 已新建 Secret Gist！")
        st.info(f"💡 将此 ID 填入 secrets.toml 的 `gist_id` 可加速后续加载：\n\n`{new_id}`")
    else:
        st.success(f"✅ 已保存 {len(store.words)} 个词")


# ═══════════════════════════════════════════════════
# WordStore（支持新 CSV 格式）
# ═══════════════════════════════════════════════════
# CSV 列顺序：word, reading, type, meaning_zh, group, long_level, added_date
# 除 word 外均可省略

class WordStore:
    def __init__(self):
        self.words = []

    def _exists(self):
        return {w["word"] for w in self.words}

    def _next_grp(self, gs=33):
        return (len(self.words) // gs) + 1

    def _make_entry(self, word, reading="", wtype="", meaning_zh="", group=None, level=0, gs=33):
        return {
            "word":       word,
            "reading":    reading,
            "type":       wtype,
            "meaning_zh": meaning_zh,
            "group":      group or self._next_grp(gs),
            "long_level": max(0, min(3, level)),
            "added_date": datetime.date.today().isoformat(),
        }

    def add_text(self, text, gs=33):
        """每行一个基本形，纯文本快速添加。"""
        ex = self._exists(); added = 0
        for line in text.splitlines():
            w = line.strip()
            if w and w not in ex:
                self.words.append(self._make_entry(w, gs=gs))
                ex.add(w); added += 1
        return added

    def import_csv(self, text, gs=33):
        ex = self._exists(); added = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("word"): continue
            parts = [p.strip() for p in line.split(",")]
            word = parts[0]
            if not word or word in ex: continue
            reading    = parts[1] if len(parts) > 1 else ""
            wtype      = parts[2] if len(parts) > 2 else ""
            meaning_zh = parts[3] if len(parts) > 3 else ""
            try:   group = int(parts[4]) if len(parts) > 4 and parts[4] else None
            except: group = None
            try:   level = int(parts[5]) if len(parts) > 5 and parts[5] else 0
            except: level = 0
            self.words.append(self._make_entry(word, reading, wtype, meaning_zh, group, level, gs))
            ex.add(word); added += 1
        return added

    def export_csv(self):
        lines = ["word,reading,type,meaning_zh,group,long_level,added_date"]
        for w in self.words:
            lines.append(",".join([
                w["word"], w.get("reading",""), w.get("type",""),
                w.get("meaning_zh",""), str(w["group"]),
                str(w["long_level"]), w.get("added_date",""),
            ]))
        return "\n".join(lines)

    def update_long(self, word, level):
        for w in self.words:
            if w["word"] == word:
                w["long_level"] = level; break

    def filter(self, levels, groups):
        return [w for w in self.words
                if w["long_level"] in levels and w["group"] in groups]

    def get(self, word):
        for w in self.words:
            if w["word"] == word: return w
        return None


# ═══════════════════════════════════════════════════
# Gemini 变形函数（含缓存）
# ═══════════════════════════════════════════════════

def _gemini_key():
    try:    return st.secrets["gemini"]["api_key"]
    except: return None

def conjugate_gemini(word_entry: dict, form: dict) -> dict:
    """
    调用 Gemini 2.0 Flash 完成变形，返回：
    {
      "word_type":  str,         # 最终词类
      "conjugated": str,         # 变形后（汉字假名）
      "reading":    str,         # 变形后读法（全平假名）
      "meanings":   [str, ...],  # 2~4 条典型用法含义
      "error":      str | None,  # 不适用时有值
    }
    结果按 "word::form_id" 缓存到 session_state.conj_cache。
    """
    cache_key = f"{word_entry['word']}::{form['id']}"
    cache = st.session_state.get("conj_cache", {})
    if cache_key in cache:
        return cache[cache_key]

    key = _gemini_key()
    if not key:
        return {"error": "未配置 Gemini API Key\n请在 secrets.toml 添加 [gemini] api_key"}

    base       = word_entry["word"]
    reading    = word_entry.get("reading") or ""
    wtype      = word_entry.get("type")    or ""
    r_hint     = f"（{reading}）" if reading else ""
    type_hint  = f"词类：{wtype}" if wtype else "词类：未知，请自行判断"

    prompt = f"""你是日语语法助手。将下面单词按指定变形类型变形，只返回 JSON，不要 markdown 或其他文字。

单词：{base}{r_hint}
{type_hint}
变形类型：{form['label']}

若该词类支持此变形，返回：
{{
  "word_type": "最终词类（中文，如 一段動詞）",
  "conjugated": "变形后（汉字假名混写，风格与原词一致）",
  "reading": "变形后完整读法（全平假名）",
  "meanings": [
    "「使用场景」：中文说明（15字以内）",
    "「使用场景」：中文说明",
    "「使用场景」：中文说明"
  ]
}}

meanings：列出 2~4 条该变形形式最典型的用法，每条注明场景（如连续动作、请求、原因、条件、否定、推量等），用中文解释。

若该词类完全不支持此变形（如 な形容詞 无 副詞形 く），返回：
{{"error": "不支持", "word_type": "..."}}"""

    # 免费额度限速重试：遇到 429 自动换模型 + 等待
    MODELS = [
        "gemini-2.0-flash-lite",   # 30 RPM 免费，优先
        "gemini-2.0-flash",        # 15 RPM，备用
        "gemini-1.5-flash-8b",     # 15 RPM，最终备用
    ]
    result = None
    for attempt in range(6):
        model = MODELS[min(attempt // 2, len(MODELS) - 1)]
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.1, "maxOutputTokens": 400}},
                timeout=20,
            )
            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                with st.spinner(f"⏳ 触发速率限制，{wait} 秒后重试（{model}）…"):
                    time.sleep(wait)
                continue
            r.raise_for_status()
            raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            result = json.loads(raw)
            break
        except Exception as e:
            if attempt >= 5:
                result = {"error": f"API 调用失败：{e}"}
    if result is None:
        result = {"error": "多次重试后仍失败，请稍后再试"}

    if "conj_cache" not in st.session_state:
        st.session_state.conj_cache = {}
    st.session_state.conj_cache[cache_key] = result
    return result


# ═══════════════════════════════════════════════════
# 随机选变形类型
# ═══════════════════════════════════════════════════

def _is_verb(wtype: str) -> bool:
    return any(k in wtype for k in VERB_TYPE_KEYS)

def _is_adj(wtype: str) -> bool:
    return any(k in wtype for k in ADJ_TYPE_KEYS)

def pick_form(word_entry: dict, enabled_verb: set, enabled_adj: set,
              exclude_id: str = None) -> dict:
    wtype = (word_entry.get("type") or "").strip()
    if _is_verb(wtype):
        pool = [f for f in VERB_FORMS if f["id"] in enabled_verb]
    elif _is_adj(wtype):
        pool = [f for f in ADJ_FORMS if f["id"] in enabled_adj]
    else:
        # 词类未知，混合全部 enabled
        pool = ([f for f in VERB_FORMS if f["id"] in enabled_verb] +
                [f for f in ADJ_FORMS  if f["id"] in enabled_adj])

    # 排除当前形（换形时避免重复）
    filtered = [f for f in pool if f["id"] != exclude_id]
    if not filtered:
        filtered = pool  # 只有一种形时允许重复
    if not filtered:
        return ALL_FORMS[0]

    weights = [f["weight"] for f in filtered]
    return random.choices(filtered, weights=weights, k=1)[0]


# ═══════════════════════════════════════════════════
# 音频生成
# ═══════════════════════════════════════════════════

def get_audio(text: str, voice: str, rate: str = "+0%") -> bytes | None:
    async def _gen():
        comm = edge_tts.Communicate(text, voice, rate=rate)
        buf  = io.BytesIO()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        return buf.read()
    try:
        return asyncio.new_event_loop().run_until_complete(_gen())
    except Exception:
        return None


# ═══════════════════════════════════════════════════
# SessionManager
# ═══════════════════════════════════════════════════

class SessionManager:
    def __init__(self, words):
        self.total    = len(words)
        self.word_map = {
            w["word"]: {**w, "state": 0, "dgr_cnt": 0}
            for w in words
        }
        groups = {}
        for w in words:
            groups.setdefault(w["group"], []).append(w["word"])
        self.group_list = [groups[k] for k in sorted(groups)]
        self.g_idx      = 0
        self.done       = 0
        self.in_loop    = False
        self.last_carryover = []
        self.queue = []
        self.q_pos = 0
        self._load_group()

    def _load_group(self):
        carry = [w for w, d in self.word_map.items() if d["state"] in (2, 3)]
        if self.g_idx >= len(self.group_list):
            self.in_loop = True
            pending = carry[:]
            if not pending: return
            random.shuffle(pending)
            self.queue = pending
        else:
            new_words = self.group_list[self.g_idx][:]
            self.g_idx += 1
            random.shuffle(new_words)
            carry_copy = carry[:]
            random.shuffle(carry_copy)
            # 每3个新词穿插1个 carry
            merged = []; ci = 0
            for i, w in enumerate(new_words):
                merged.append(w)
                if (i + 1) % 3 == 0 and ci < len(carry_copy):
                    merged.append(carry_copy[ci]); ci += 1
            merged.extend(carry_copy[ci:])
            self.queue = merged
        self.last_carryover = [w for w in self.queue if self.word_map[w]["state"] in (2, 3)]
        self.q_pos = 0

    def current_word(self):
        return self.queue[self.q_pos] if self.q_pos < len(self.queue) else None

    def word_detail(self, word):
        return self.word_map.get(word, {})

    def stats(self):
        return {
            "gid":       self.g_idx if not self.in_loop else None,
            "queue_rem": len(self.queue) - self.q_pos,
            "done":      self.done,
            "total":     self.total,
            "in_loop":   self.in_loop,
        }

    def rate(self, word, lv):
        d = self.word_map[word]
        if lv == 1:
            if d["state"] != 1:
                d["state"] = 1; self.done += 1
            self.q_pos += 1
        else:
            d["state"]   = lv
            d["dgr_cnt"] = d.get("dgr_cnt", 0) + 1
            # 模糊→隔3个重复，不会→隔1个重复
            insert_at = self.q_pos + 1 + (3 if lv == 2 else 1)
            self.queue.insert(min(insert_at, len(self.queue)), word)
            self.q_pos += 1

        if all(d["state"] == 1 for d in self.word_map.values()):
            return "session_done"
        if self.q_pos >= len(self.queue):
            self._load_group()
            return "group_done"
        return "ok"

    def skip(self):
        self.q_pos += 1
        if self.q_pos >= len(self.queue):
            pending = [w for w, d in self.word_map.items() if d["state"] != 1]
            if not pending: return "session_done"
            self._load_group()
            return "group_done"
        return "ok"

    def prev(self):
        if self.q_pos > 0:
            self.q_pos -= 1; return True
        return False


# ═══════════════════════════════════════════════════
# Session State 初始化
# ═══════════════════════════════════════════════════

def _init():
    defaults = {
        "phase":          "main",
        "store":          WordStore(),
        "session":        None,
        "voice":          "ja-JP-NanamiNeural",
        "speed":          "+0%",
        "gist_id":        None,
        "gist_last_sync": None,
        "conj_cache":     {},
        "cur_audio":      None,
        "last_audio_key": "",
        "autoplay":       False,
        "show_answer":    False,
        "cur_conj":       None,
        "cur_form":       None,
        "rv_idx":         0,
        "enabled_verb":   {"te","past","nai","masu","potential","passive","causative","ba"},
        "enabled_adj":    {"adj_neg","adj_past","adj_adv","adj_te"},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


# ═══════════════════════════════════════════════════
# 界面：主页
# ═══════════════════════════════════════════════════

def screen_main():
    store = st.session_state.store
    st.title("🇯🇵 日语变形听力练习")

    # ── Gist 同步 ──────────────────────────────────
    with st.expander("☁️ GitHub Gist 同步", expanded=False):
        if _gist_enabled():
            c1, c2 = st.columns(2)
            with c1:
                if st.button("📥 从 Gist 加载", use_container_width=True): do_gist_load()
            with c2:
                if st.button("📤 保存到 Gist", use_container_width=True): do_gist_save()
            if st.session_state.gist_last_sync:
                st.caption(f"上次同步：{st.session_state.gist_last_sync}")
        else:
            st.caption("在 secrets.toml 配置 `[github] token` 后可使用云同步")

    # ── 词库管理 ───────────────────────────────────
    with st.expander("📚 词库管理", expanded=not bool(store.words)):
        st.caption(
            "CSV 格式（可粘贴到 Excel 另存）：\n"
            "`word,reading,type,meaning_zh`\n"
            "后三列**可省略**，AI 会自动判断词类"
        )
        tab_csv, tab_text = st.tabs(["上传 CSV", "粘贴纯文本"])
        with tab_csv:
            f = st.file_uploader("选择 CSV 文件", type="csv",
                                 label_visibility="collapsed")
            if f:
                n = store.import_csv(f.read().decode("utf-8"))
                st.success(f"✅ 导入 {n} 个词"); st.rerun()
        with tab_text:
            st.caption("每行一个基本形（仅词形）")
            txt = st.text_area("粘贴词汇", height=120, label_visibility="collapsed")
            if st.button("添加", use_container_width=True):
                n = store.add_text(txt)
                st.success(f"✅ 添加 {n} 个词"); st.rerun()

        if store.words:
            st.divider()
            col_dl, col_clr = st.columns(2)
            with col_dl:
                st.download_button("⬇ 下载 CSV", data=store.export_csv(),
                                   file_name="japanese_inflection_words.csv",
                                   mime="text/csv", use_container_width=True)
            with col_clr:
                if st.button("🗑 清空词库", use_container_width=True):
                    st.session_state.store = WordStore(); st.rerun()

    if not store.words:
        st.info("👆 请先导入词库")
        return

    st.markdown(f"词库共 **{len(store.words)}** 个词")

    # ── 变形类型选择 ───────────────────────────────
    with st.expander("⚙️ 练习设置", expanded=False):
        st.caption("**动词变形**（★★★=主要 权重×3，★=次要 权重×1）")
        ev = set(st.session_state.enabled_verb)
        cols = st.columns(4)
        for i, f in enumerate(VERB_FORMS):
            star = "★★★" if f["weight"] == 3 else "★"
            if cols[i % 4].checkbox(f"{star} {f['label']}", value=f["id"] in ev,
                                    key=f"vf_{f['id']}"):
                ev.add(f["id"])
            else:
                ev.discard(f["id"])
        if not ev:
            ev = {"te"}  # 至少保留一个
        st.session_state.enabled_verb = ev

        st.caption("**形容词变形**")
        ea = set(st.session_state.enabled_adj)
        cols2 = st.columns(4)
        for i, f in enumerate(ADJ_FORMS):
            if cols2[i % 4].checkbox(f["label"], value=f["id"] in ea,
                                     key=f"af_{f['id']}"):
                ea.add(f["id"])
            else:
                ea.discard(f["id"])
        if not ea:
            ea = {"adj_neg"}
        st.session_state.enabled_adj = ea

    # ── 筛选 & 开始 ────────────────────────────────
    groups = {}
    for w in store.words:
        groups.setdefault(w["group"], []).append(w)

    lv_map = {0:"0 新词", 1:"1 已掌握", 2:"2 模糊", 3:"3 重点"}
    lv_sel = st.multiselect("长期等级筛选", options=[0,1,2,3], default=[0,2,3],
                             format_func=lambda x: lv_map[x])
    gr_sel = st.multiselect(
        "分组筛选", options=sorted(groups), default=sorted(groups),
        format_func=lambda x: f"第 {x} 组（{len(groups[x])} 词）",
        label_visibility="collapsed",
    )
    voice_name = st.selectbox("语音", list(VOICES.keys()))

    ws = store.filter(lv_sel, gr_sel)
    if ws:
        st.info(f"🎯 将练习 **{len(ws)}** 个词")
    else:
        st.warning("⚠️ 无词匹配，请调整筛选条件")

    if st.button("🎧 开始练习", type="primary",
                 disabled=(not ws), use_container_width=True):
        st.session_state.voice          = VOICES[voice_name]
        st.session_state.session        = SessionManager(ws)
        st.session_state.show_answer    = False
        st.session_state.last_audio_key = ""
        st.session_state.cur_conj       = None
        st.session_state.cur_form       = None
        st.session_state.phase          = "session"
        st.rerun()


# ═══════════════════════════════════════════════════
# 界面：练习
# ═══════════════════════════════════════════════════

def screen_session():
    sess = st.session_state.session
    if not sess:
        st.session_state.phase = "main"; st.rerun()

    word = sess.current_word()
    if not word: return
    word_entry = st.session_state.store.get(word) or sess.word_map[word]

    # ── 计算 audio_key，决定是否重新选形 + 调 API ──
    cur_form = st.session_state.cur_form
    audio_key = f"{word}::{cur_form['id'] if cur_form else ''}"

    need_regen = (st.session_state.last_audio_key != audio_key
                  or st.session_state.cur_conj is None)

    if need_regen:
        # 选形（排除当前形，避免"换形"时重复）
        form = pick_form(
            word_entry,
            st.session_state.enabled_verb,
            st.session_state.enabled_adj,
            exclude_id=cur_form["id"] if cur_form else None,
        )
        st.session_state.cur_form  = form
        st.session_state.show_answer = False

        # 调 Gemini，最多重试 3 次（遇到"不支持"时换形）
        conj = None
        tried = set()
        for _ in range(3):
            with st.spinner(f"🤖 AI 变形中（{form['label']}）…"):
                conj = conjugate_gemini(word_entry, form)
            if not conj.get("error"):
                break
            tried.add(form["id"])
            form = pick_form(word_entry,
                             st.session_state.enabled_verb,
                             st.session_state.enabled_adj,
                             exclude_id=None)
            if form["id"] in tried:
                break  # 避免死循环
            st.session_state.cur_form = form

        st.session_state.cur_conj = conj

        # 生成音频（用变形后的词）
        speak_text = conj.get("conjugated", word) if not conj.get("error") else word
        with st.spinner("🎵 生成音频…"):
            st.session_state.cur_audio = get_audio(
                speak_text, st.session_state.voice, st.session_state.speed)

        st.session_state.last_audio_key = f"{word}::{st.session_state.cur_form['id']}"
        st.session_state.autoplay = True

    form = st.session_state.cur_form
    conj = st.session_state.cur_conj
    error = conj.get("error") if conj else "未获取到变形结果"

    # ── 顶部进度 ─────────────────────────────────
    s   = sess.stats()
    det = sess.word_detail(word)
    _sl = {0:"⬜ 新词", 1:"✅ 认识", 2:"🟡 模糊", 3:"❌ 不会"}
    gstr = f"第 {s['gid']} 组" if s["gid"] else "🔁 收尾循环"
    dgr_tip = f" · 降级 {det['dgr_cnt']} 次" if det.get("dgr_cnt") else ""
    st.caption(
        f"**{gstr}** · 队列剩余 {s['queue_rem']} · "
        f"已通过 {s['done']}/{s['total']} · "
        f"{_sl.get(det['state'], '')} {dgr_tip}"
    )
    st.progress(s["done"] / max(s["total"], 1))

    # ── 变形标签 ─────────────────────────────────
    form_label = form["label"] if form else "—"
    st.markdown(
        f"<div style='text-align:center;margin-bottom:4px'>"
        f"<span class='form-tag'>{form_label}</span></div>",
        unsafe_allow_html=True
    )

    # ── 主显示：变形后的词（默认模糊） ───────────
    show = st.session_state.get("show_answer", False)
    if error:
        st.markdown(
            f"<div class='word-box' style='font-size:18px;color:gray;'>{error}</div>",
            unsafe_allow_html=True
        )
    else:
        conjugated = conj.get("conjugated", "…")
        cls = "" if show else " hidden"
        st.markdown(f"<div class='word-box{cls}'>{conjugated}</div>",
                    unsafe_allow_html=True)

    # ── 音频 ─────────────────────────────────────
    autoplay = st.session_state.get("autoplay", False)
    st.session_state.autoplay = False
    if st.session_state.cur_audio:
        st.audio(st.session_state.cur_audio, format="audio/mpeg", autoplay=autoplay)
    else:
        st.caption("⚠️ 音频未生成" + (f"（{error}）" if error else ""))

    col_spd, col_rp, col_chg = st.columns([3, 1, 1])
    with col_spd:
        spd_name = st.selectbox(
            "速度", list(SPEEDS.keys()),
            index=list(SPEEDS.values()).index(st.session_state.speed),
            label_visibility="collapsed",
        )
        st.session_state.speed = SPEEDS[spd_name]
    with col_rp:
        if st.button("🔊 重播", use_container_width=True):
            st.session_state.autoplay = True; st.rerun()
    with col_chg:
        if st.button("🔀 换形", use_container_width=True):
            st.session_state.cur_conj = None
            st.session_state.last_audio_key = ""
            st.rerun()

    st.divider()

    # ── 答案展开区 ───────────────────────────────
    if st.toggle("👁 显示答案", value=show, key="show_answer"):
        if not error and conj:
            reading_base = word_entry.get("reading", "")
            meaning_base = word_entry.get("meaning_zh", "")
            wtype_final  = conj.get("word_type") or word_entry.get("type") or "未知"
            reading_conj = conj.get("reading", "")
            meanings     = conj.get("meanings", [])

            col_base, col_conj = st.columns(2)
            with col_base:
                st.markdown("**基本形**")
                st.markdown(f"#### {word}")
                if reading_base: st.caption(f"読み：{reading_base}")
                if meaning_base: st.caption(f"🈶 {meaning_base}")
                st.caption(f"词类：{wtype_final}")
            with col_conj:
                st.markdown(f"**{form_label}**")
                st.markdown(f"#### {conj.get('conjugated', '')}")
                if reading_conj: st.caption(f"読み：{reading_conj}")

            if meanings:
                st.markdown("**变形后可能的含义 / 用法**")
                for m in meanings:
                    st.markdown(
                        f"<div class='meaning-row'>・{m}</div>",
                        unsafe_allow_html=True
                    )

    st.divider()
    st.caption("**评级** — 评级后自动跳到下一词")

    def do_rate(lv):
        st.session_state.show_answer    = False
        st.session_state.cur_conj       = None
        st.session_state.cur_form       = None
        st.session_state.last_audio_key = ""
        result = sess.rate(word, lv)
        if result == "session_done":
            st.session_state.phase = "done"
            if _gist_enabled(): do_gist_save()
        elif result == "group_done":
            st.session_state.phase = "group_done"
        st.rerun()

    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        if st.button("① 听懂了", use_container_width=True, type="secondary"): do_rate(1)
    with bc2:
        if st.button("② 不确定", use_container_width=True): do_rate(2)
    with bc3:
        if st.button("③ 没听懂", use_container_width=True, type="primary"): do_rate(3)

    nc1, nc2, nc3 = st.columns(3)
    with nc1:
        if st.button("◀ 上一", disabled=(sess.q_pos == 0), use_container_width=True):
            if sess.prev():
                st.session_state.cur_conj = None
                st.session_state.cur_form = None
                st.session_state.last_audio_key = ""
                st.rerun()
    with nc2:
        pass  # 中间留空（换形按钮已在上方）
    with nc3:
        if st.button("⏹ 退出", use_container_width=True):
            st.session_state.phase = "main"
            st.session_state.session = None; st.rerun()

    # ── 长期评级 ─────────────────────────────────
    cur_lv = sess.word_map[word]["long_level"]
    with st.expander(f"长期评级（当前 {cur_lv} 级）"):
        lv_map = {0:"0 新词", 1:"1 掌握", 2:"2 模糊", 3:"3 重点"}
        cols = st.columns(4)
        for lv, col in zip([0,1,2,3], cols):
            btype = "primary" if lv == cur_lv else "secondary"
            if col.button(lv_map[lv], key=f"long_{lv}",
                          use_container_width=True, type=btype):
                st.session_state.store.update_long(word, lv)
                st.toast(f"✅ 已标记为长期 {lv} 级")
                st.rerun()


# ═══════════════════════════════════════════════════
# 界面：组间过渡
# ═══════════════════════════════════════════════════

def screen_group_done():
    sess = st.session_state.session
    if not sess:
        st.session_state.phase = "main"; st.rerun()
    s     = sess.stats()
    carry = sess.last_carryover
    if s["in_loop"]:
        st.info(f"🔁 **进入收尾循环** — {len(carry)} 个词将继续出现，直到全部通过")
    else:
        st.info(f"📋 **进入第 {s['gid']} 组** — {len(carry)} 个词将混入新组")
    st.markdown(f"已通过：**{s['done']}** / {s['total']}")
    if carry:
        st.markdown("**未完成词：** " + "　".join(carry))
    else:
        st.success("✅ 上一组全部通过！")
    c1, c2 = st.columns(2)
    if c1.button("继续 ▶", type="primary", use_container_width=True):
        st.session_state.cur_conj = None
        st.session_state.cur_form = None
        st.session_state.last_audio_key = ""
        st.session_state.phase = "session"; st.rerun()
    if c2.button("⏹ 退出练习", use_container_width=True):
        st.session_state.phase = "main"; st.session_state.session = None; st.rerun()


# ═══════════════════════════════════════════════════
# 界面：完成
# ═══════════════════════════════════════════════════

def screen_done():
    sess = st.session_state.session
    if not sess:
        st.session_state.phase = "main"; st.rerun()
    s = sess.stats()
    st.balloons()
    st.success(f"🎉 练习完成！共 {s['total']} 个词全部通过 ✓")

    all_words = sorted(sess.word_map.values(), key=lambda w: -w["long_level"])
    lv_names  = {0:"新词", 1:"已掌握", 2:"模糊", 3:"重点"}
    st.subheader("词汇总览")
    for lv in [3, 2, 1, 0]:
        ws = [w["word"] for w in all_words if w["long_level"] == lv]
        if ws:
            st.markdown(f"**{lv}级 {lv_names[lv]}（{len(ws)}个）** " + "　".join(ws))

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if _gist_enabled():
            if st.button("🐙 保存到 GitHub Gist", type="primary", use_container_width=True):
                do_gist_save()
    with c2:
        st.download_button("⬇ 下载 CSV",
                           data=st.session_state.store.export_csv(),
                           file_name="japanese_inflection_words.csv",
                           mime="text/csv", use_container_width=True)

    if st.button("🏠 返回主页", use_container_width=True):
        st.session_state.phase = "main"
        st.session_state.session = None
        st.session_state.rv_idx  = 0; st.rerun()


# ═══════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════
{
    "main":       screen_main,
    "session":    screen_session,
    "group_done": screen_group_done,
    "done":       screen_done,
}.get(st.session_state.phase, screen_main)()
