# ═══════════════════════════════════════════════════
# 日语单词听力练习系统 v3.0  (Streamlit 版)
# 从 Colab/ipywidgets 完整移植，逻辑完全保留
# ═══════════════════════════════════════════════════
import streamlit as st
import edge_tts
import asyncio
import io
import base64
import random
import datetime

# ── 页面配置（必须在所有其他 st 调用之前）──────────
st.set_page_config(
    page_title="日语听力练习",
    page_icon="🇯🇵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── 全局 CSS ─────────────────────────────────────────
st.markdown("""
<style>
  /* 大字单词区 */
  .word-box {
      text-align: center;
      font-size: 64px;
      font-weight: 700;
      color: #2c3e50;
      letter-spacing: 4px;
      padding: 24px 0 18px;
      min-height: 110px;
      line-height: 1.1;
      font-family: 'Helvetica Neue', Arial, 'Hiragino Sans', sans-serif;
  }
  .word-box.hidden {
      color: #ecf0f1;
      text-shadow: 0 0 28px #bdc3c7;
  }
  /* 统一按钮圆角 */
  div.stButton > button { border-radius: 10px; }
  /* 音频播放器宽度 */
  audio { width: 100% !important; }
</style>
""", unsafe_allow_html=True)

# ── 常量 ──────────────────────────────────────────────
VOICES = {
    "🎀 七海 Nanami（女声·自然）": "ja-JP-NanamiNeural",
    "🎵 圭太 Keita（男声·自然）":  "ja-JP-KeitaNeural",
}
SPEEDS = {
    "🐢 0.75× 慢速": "-25%",
    "🐇 0.9×  稍慢": "-10%",
    "▶  1.0×  正常": "+0%",
    "⚡ 1.15× 稍快": "+15%",
    "🚀 1.3×  快速": "+30%",
}

# ═══════════════════════════════════════════════════
# WordStore — 与原版完全相同
# ═══════════════════════════════════════════════════
class WordStore:
    def __init__(self):
        self.words = []

    def _exists(self):
        return {w['word'] for w in self.words}

    def _next_grp(self, gs):
        return (len(self.words) // gs) + 1

    def add_text(self, text, gs=33):
        ex = self._exists()
        added = 0
        for line in text.splitlines():
            w = line.strip()
            if w and w not in ex:
                self.words.append({
                    'word': w, 'group': self._next_grp(gs),
                    'long_level': 0,
                    'added_date': datetime.date.today().isoformat()
                })
                ex.add(w)
                added += 1
        return added

    def import_csv(self, text, gs=33):
        ex = self._exists()
        added = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('word'):
                continue
            parts = line.split(',')
            word = parts[0].strip()
            if not word or word in ex:
                continue
            try:
                group = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else self._next_grp(gs)
            except Exception:
                group = self._next_grp(gs)
            try:
                level = max(0, min(3, int(parts[2].strip()))) if len(parts) > 2 else 0
            except Exception:
                level = 0
            date = parts[3].strip() if len(parts) > 3 else datetime.date.today().isoformat()
            self.words.append({
                'word': word, 'group': group,
                'long_level': level, 'added_date': date
            })
            ex.add(word)
            added += 1
        return added

    def update_long(self, word, level):
        for w in self.words:
            if w['word'] == word:
                w['long_level'] = level
                return

    def get_groups(self):
        gs = {}
        for w in self.words:
            gs.setdefault(w['group'], []).append(w)
        return dict(sorted(gs.items()))

    def filter(self, levels, groups):
        return [w for w in self.words
                if w['long_level'] in levels and w['group'] in groups]

    def export_csv(self):
        lines = ['word,group,long_level,added_date']
        for w in self.words:
            lines.append(f"{w['word']},{w['group']},{w['long_level']},{w['added_date']}")
        return '\n'.join(lines)

    def stats(self):
        lv = [0, 0, 0, 0]
        for w in self.words:
            lv[w['long_level']] += 1
        return {
            'total':  len(self.words),
            'levels': lv,
            'groups': len(set(w['group'] for w in self.words))
        }


# ═══════════════════════════════════════════════════
# SessionManager — 与原版完全相同
# ═══════════════════════════════════════════════════
_INIT_STATE = {0: 3, 1: 1, 2: 2, 3: 3}
_REAPPEAR = {
    3: [('near',   4,  8), ('medium', 14, 22)],
    2: [('medium', 10, 17)],
    1: [],
}
_CARRYOVER_SLOTS = {3: 2, 2: 1}

class SessionManager:
    def __init__(self, words):
        self.word_map  = {w['word']: w for w in words}
        self.state     = {w['word']: _INIT_STATE[w['long_level']] for w in words}
        self.done      = {w['word']: (w['long_level'] == 1) for w in words}
        self.dgr       = {w['word']: {} for w in words}
        self.history   = {w['word']: [] for w in words}
        gmap = {}
        for w in words:
            gmap.setdefault(w['group'], []).append(w['word'])
        self.group_order    = sorted(gmap.keys())
        self.gmap           = gmap
        self.g_idx          = 0
        self.carryover      = {}
        self.last_carryover = []
        self.queue          = []
        self.q_pos          = 0
        self.in_loop        = False
        self._build_queue()

    def _build_queue(self):
        gid  = self.group_order[self.g_idx]
        main = [w for w in self.gmap[gid] if not self.done[w]]
        random.shuffle(main)
        combined = list(main)
        for w, slots in self.carryover.items():
            for _ in range(slots):
                combined.insert(random.randint(0, len(combined)), w)
        self.carryover = {}
        self.queue = combined
        self.q_pos = 0

    def current_word(self):
        return self.queue[self.q_pos] if self.q_pos < len(self.queue) else None

    def _reinsert(self, word):
        st_val = self.state[word]
        for (_, lo, hi) in _REAPPEAR.get(st_val, []):
            dist = max(3, random.randint(lo, hi))
            pos  = min(self.q_pos + dist, len(self.queue))
            self.queue.insert(pos, word)

    def rate(self, word, button):
        self.history[word].append(button)
        curr = self.state[word]
        if button < curr:
            self.state[word] = button
            self.dgr[word]   = {}
        elif button > curr:
            self.dgr[word][button] = self.dgr[word].get(button, 0) + 1
            if self.dgr[word][button] >= 3:
                self.state[word] = min(3, curr + 1)
                self.dgr[word]   = {}
        else:
            self.dgr[word] = {}
        if self.state[word] == 1:
            self.done[word] = True
        else:
            self.done[word] = False
            self._reinsert(word)
        self.q_pos += 1
        if self.is_done():
            return 'session_done'
        if self.q_pos >= len(self.queue):
            return self._advance()
        return 'continue'

    def _advance(self):
        if self.in_loop:
            undone = [w for w, d in self.done.items() if not d]
            if undone:
                random.shuffle(undone)
                self.queue = undone
                self.q_pos = 0
                return 'continue'
            return 'session_done'
        gid = self.group_order[self.g_idx]
        new_carry = {}
        self.last_carryover = []
        for w in self.gmap[gid]:
            st_val = self.state[w]
            if not self.done[w] and st_val in _CARRYOVER_SLOTS:
                new_carry[w] = _CARRYOVER_SLOTS[st_val]
                self.last_carryover.append(w)
        self.g_idx += 1
        if self.g_idx < len(self.group_order):
            self.carryover = new_carry
            self._build_queue()
            return 'group_done'
        else:
            undone = [w for w, d in self.done.items() if not d]
            if undone:
                self.in_loop = True
                self.last_carryover = list(undone)
                random.shuffle(undone)
                self.queue = undone
                self.q_pos = 0
                return 'group_done'
            return 'session_done'

    def is_done(self):
        return all(self.done.values())

    def prev(self):
        if self.q_pos > 0:
            self.q_pos -= 1
            return True
        return False

    def skip(self):
        word = self.current_word()
        if word:
            self._reinsert(word)
        self.q_pos += 1
        if self.is_done():
            return 'session_done'
        if self.q_pos >= len(self.queue):
            return self._advance()
        return 'continue'

    def current_gid(self):
        if self.in_loop or self.g_idx >= len(self.group_order):
            return None
        return self.group_order[self.g_idx]

    def word_detail(self, word):
        return {
            'state':   self.state.get(word, 1),
            'hist':    self.history.get(word, []),
            'dgr_cnt': sum(self.dgr.get(word, {}).values()),
        }

    def stats(self):
        done  = sum(1 for d in self.done.values() if d)
        total = len(self.done)
        return {
            'done':         done,
            'total':        total,
            'undone_count': total - done,
            'queue_rem':    max(0, len(self.queue) - self.q_pos),
            'in_loop':      self.in_loop,
            'gid':          self.current_gid(),
        }


# ═══════════════════════════════════════════════════
# TTS — 用 @st.cache_data 自动缓存，最多150条
# ═══════════════════════════════════════════════════
def _tts_in_thread(word: str, voice: str, rate: str) -> bytes:
    """
    在独立线程里跑 edge-tts，完全隔离 Streamlit/tornado 的事件循环。
    加 15 秒超时；失败返回 b'' 而不抛异常。
    """
    import threading
    result_box: list = [b""]
    error_box:  list = [None]

    async def _stream():
        com = edge_tts.Communicate(word, voice, rate=rate)
        buf = io.BytesIO()
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    def _worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_box[0] = loop.run_until_complete(_stream())
        except Exception as e:
            error_box[0] = e
        finally:
            loop.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=15)
    if not t.is_alive() and not error_box[0]:
        return result_box[0]
    return b""


def render_audio(data: bytes, autoplay: bool = False) -> None:
    """
    用原始 HTML <audio> 渲染音频，兼容 iOS/Android 移动端。
    st.audio() 在部分移动浏览器上有 MIME 兼容问题，HTML 更可靠。
    """
    if not data:
        st.caption("⚠️ 音频未生成，请点「🔊 重播」重试")
        return
    b64  = base64.b64encode(data).decode()
    auto = "autoplay" if autoplay else ""
    st.markdown(
        f'<audio controls {auto} style="width:100%;border-radius:8px;margin:4px 0">'
        f'<source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg">'
        f'<source src="data:audio/mp3;base64,{b64}" type="audio/mp3">'
        f'</audio>'
        f'<p style="font-size:11px;color:#888;margin:0">音频大小：{len(data)//1024} KB</p>',
        unsafe_allow_html=True,
    )


@st.cache_data(max_entries=150, show_spinner=False)
def get_audio(word: str, voice: str, rate: str) -> bytes:
    """带 Streamlit 级缓存的 TTS，最多保留 150 条，跨 rerun 复用。"""
    return _tts_in_thread(word, voice, rate)


# ═══════════════════════════════════════════════════
# Session State 初始化
# ═══════════════════════════════════════════════════
def _init():
    defaults = {
        'store':     WordStore(),
        'session':   None,
        'phase':     'main',      # main | session | group_done | done
        'show_word': False,
        'voice':     'ja-JP-NanamiNeural',
        'speed':     '+0%',
        'gs':        33,
        'autoplay':  False,       # 控制 st.audio 是否自动播放
        'rv_idx':    0,           # 完成界面复习索引
        'cur_audio': b'',         # 当前单词的音频字节
        # 文件上传去重
        'last_file_id':     '',
        'last_file_result': None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


# ── 工具函数：加载当前词的音频并标记自动播放 ──────────
def _load_audio():
    sess = st.session_state.session
    if not sess:
        return
    word = sess.current_word()
    if word:
        st.session_state.cur_audio = get_audio(
            word, st.session_state.voice, st.session_state.speed)
        st.session_state.autoplay = True


# ═══════════════════════════════════════════════════
# 界面：主页
# ═══════════════════════════════════════════════════
def screen_main():
    store = st.session_state.store
    s = store.stats()

    st.title("🇯🇵 日语单词听力练习")

    # 词库概况
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("总词数", s['total'])
    c2.metric("0级 新词", s['levels'][0])
    c3.metric("1级 掌握", s['levels'][1])
    c4.metric("2级 模糊", s['levels'][2])
    c5.metric("3级 重点", s['levels'][3])

    tab_in, tab_st = st.tabs(["📝 录入词汇", "🎧 开始学习"])
    with tab_in:
        _panel_input()
    with tab_st:
        _panel_study()


# ── 录入面板 ─────────────────────────────────────────
def _panel_input():
    store = st.session_state.store

    # 粘贴添加
    st.subheader("粘贴添加")
    raw  = st.text_area("每行一个日语词", height=130, label_visibility="collapsed",
                         placeholder="食べる\n飲む\nきれい\n勉強する")
    gs_v = st.number_input("每组词数", min_value=5, max_value=200,
                            value=st.session_state.gs, step=1)

    if st.button("➕ 添加词汇", type="primary"):
        n = store.add_text(raw, int(gs_v))
        st.session_state.gs = int(gs_v)
        if n:
            st.success(f"✅ 添加了 {n} 个新词")
        else:
            st.warning("⚠️ 没有新词（词可能已存在）")

    st.divider()

    # CSV 上传
    st.subheader("📂 上传词库 CSV（推荐持续学习）")
    st.caption("上传之前导出的 CSV，组别和长期等级将完整保留。")
    uploaded = st.file_uploader("选择 CSV 文件", type=["csv"],
                                 label_visibility="collapsed")
    if uploaded is not None:
        # 用文件名+大小去重，避免每次 rerun 重复导入
        file_id = f"{uploaded.name}_{uploaded.size}"
        if st.session_state.last_file_id != file_id:
            try:
                text = uploaded.read().decode("utf-8-sig")
                n    = store.import_csv(text, int(gs_v))
                st.session_state.last_file_id     = file_id
                st.session_state.last_file_result = (uploaded.name, n)
            except Exception as e:
                st.error(f"读取失败：{e}")
        if st.session_state.last_file_result:
            fname, n = st.session_state.last_file_result
            if n:
                st.success(f"✅ 从 {fname} 导入了 {n} 个词，组别和等级已完整保留")
            else:
                st.info(f"文件 {fname} 中没有新词（可能已全部存在）")

    st.divider()

    # 词库预览 + 导出
    st.subheader("当前词库")
    groups = store.get_groups()
    if not groups:
        st.caption("（词库为空，请先添加词汇）")
    else:
        lv_icon = {0: "⬜", 1: "🟩", 2: "🟨", 3: "🟥"}
        for gid, words in groups.items():
            with st.expander(f"第 {gid} 组 — {len(words)} 词"):
                st.write("　".join(
                    f"{lv_icon[w['long_level']]} {w['word']}" for w in words))

        st.download_button(
            "⬇ 导出词库 CSV",
            data=store.export_csv(),
            file_name="japanese_words.csv",
            mime="text/csv",
            use_container_width=True,
        )


# ── 学习配置面板 ──────────────────────────────────────
def _panel_study():
    store = st.session_state.store
    if not store.words:
        st.warning("⚠️ 请先在「录入词汇」标签页添加词汇")
        return

    groups  = store.get_groups()
    all_gids = list(groups.keys())

    # 长期等级筛选
    st.caption("**筛选长期等级**")
    lc = st.columns(4)
    lv_labels   = ["0 新词", "1 掌握", "2 模糊", "3 重点"]
    lv_defaults = [True,     False,    True,     True]
    lv_sel = [i for i, (col, lbl, df) in enumerate(zip(lc, lv_labels, lv_defaults))
               if col.checkbox(lbl, value=df, key=f"lv_chk_{i}")]

    # 组别筛选
    st.caption("**筛选组别**")
    gr_sel = st.multiselect(
        "组别", all_gids, default=all_gids,
        format_func=lambda x: f"第{x}组 ({len(groups[x])}词)",
        label_visibility="collapsed",
    )

    # 语音选择
    voice_name = st.selectbox("语音", list(VOICES.keys()))

    # 预览匹配词数
    ws = store.filter(lv_sel, gr_sel)
    if ws:
        st.info(f"🎯 将练习 **{len(ws)}** 个词")
    else:
        st.warning("⚠️ 无词匹配，请调整筛选条件")

    if st.button("🎧 开始练习", type="primary",
                  disabled=(not ws), use_container_width=True):
        st.session_state.voice   = VOICES[voice_name]
        st.session_state.session = SessionManager(ws)
        st.session_state.show_word = False
        st.session_state.phase   = 'session'
        _load_audio()
        st.rerun()


# ═══════════════════════════════════════════════════
# 界面：练习
# ═══════════════════════════════════════════════════
def screen_session():
    sess = st.session_state.session
    if not sess:
        st.session_state.phase = 'main'
        st.rerun()

    s    = sess.stats()
    word = sess.current_word()
    if not word:
        return

    det  = sess.word_detail(word)
    _sl  = {1: "✅ 认识", 2: "🟡 模糊", 3: "❌ 不会"}
    gstr = f"第 {s['gid']} 组" if s['gid'] else "🔁 收尾循环"

    # ── 状态栏 ────────────────────────────────────────
    dgr_tip = f" · 降级进度 {det['dgr_cnt']}/3" if det['dgr_cnt'] else ""
    st.caption(
        f"**{gstr}** · 队列剩余 {s['queue_rem']} · "
        f"已通过 {s['done']}/{s['total']} · "
        f"{_sl[det['state']]}{dgr_tip}"
    )
    st.progress(s['done'] / max(s['total'], 1))

    # ── 单词显示 ──────────────────────────────────────
    cls = "" if st.session_state.show_word else " hidden"
    txt = word if st.session_state.show_word else "？"
    st.markdown(f'<div class="word-box{cls}">{txt}</div>',
                unsafe_allow_html=True)

    # ── 音频播放器 ────────────────────────────────────
    # autoplay 仅在换词时为 True，切换显词/其他操作时为 False，避免重复播放
    autoplay = st.session_state.autoplay
    st.session_state.autoplay = False     # 立即重置，下次 rerun 不重播

    if st.session_state.cur_audio:
        render_audio(st.session_state.cur_audio, autoplay=autoplay)
    else:
        st.caption("⚠️ 音频未生成，请点「🔊 重播」")

    # ── 速度 + 重播 ───────────────────────────────────
    col_sp, col_rp = st.columns([3, 1])
    with col_sp:
        spd_name = st.selectbox(
            "速度", list(SPEEDS.keys()),
            index=list(SPEEDS.values()).index(st.session_state.speed),
            label_visibility="collapsed",
        )
        st.session_state.speed = SPEEDS[spd_name]
    with col_rp:
        if st.button("🔊 重播", use_container_width=True):
            st.session_state.cur_audio = get_audio(
                word, st.session_state.voice, st.session_state.speed)
            st.session_state.autoplay = True
            st.rerun()

    st.divider()

    # ── 短期评级 ──────────────────────────────────────
    st.caption("**短期评级** — 立即影响播放队列")

    def do_rate(lv):
        st.session_state.show_word = False
        result = sess.rate(word, lv)
        if result == 'session_done':
            st.session_state.phase = 'done'
        elif result == 'group_done':
            st.session_state.phase = 'group_done'
        else:
            _load_audio()
        st.rerun()

    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        if st.button("① 认识", use_container_width=True, type="secondary"):
            do_rate(1)
    with bc2:
        if st.button("② 模糊", use_container_width=True):
            do_rate(2)
    with bc3:
        if st.button("③ 不会", use_container_width=True, type="primary"):
            do_rate(3)

    # ── 导航行 ───────────────────────────────────────
    nc1, nc2, nc3, nc4 = st.columns(4)
    with nc1:
        if st.button("◀ 上一", disabled=(sess.q_pos == 0),
                     use_container_width=True):
            if sess.prev():
                st.session_state.show_word = False
                _load_audio()
                st.rerun()
    with nc2:
        # 不用 key=，手动同步，这样 do_rate 里才能直接赋值 show_word=False
        new_show = st.toggle("👁 显词", value=st.session_state.show_word)
        st.session_state.show_word = new_show
    with nc3:
        if st.button("跳过 ▶", use_container_width=True):
            result = sess.skip()
            st.session_state.show_word = False
            if result == 'session_done':
                st.session_state.phase = 'done'
            elif result == 'group_done':
                st.session_state.phase = 'group_done'
            else:
                _load_audio()
            st.rerun()
    with nc4:
        if st.button("⏹ 退出", use_container_width=True):
            st.session_state.phase   = 'main'
            st.session_state.session = None
            st.rerun()

    # ── 长期评级（折叠）─────────────────────────────
    cur_lv = sess.word_map[word]['long_level']
    with st.expander(f"长期评级（当前 {cur_lv} 级）"):
        lv_map = {0: "0 新词", 1: "1 掌握", 2: "2 模糊", 3: "3 重点"}
        lc1, lc2, lc3, lc4 = st.columns(4)
        for lv, col in zip([0, 1, 2, 3], [lc1, lc2, lc3, lc4]):
            btn_type = "primary" if lv == cur_lv else "secondary"
            if col.button(lv_map[lv], key=f"long_{lv}",
                          use_container_width=True, type=btn_type):
                st.session_state.store.update_long(word, lv)
                st.toast(f"✅ 已保存为长期 {lv} 级")
                st.rerun()


# ═══════════════════════════════════════════════════
# 界面：组间过渡
# ═══════════════════════════════════════════════════
def screen_group_done():
    sess = st.session_state.session
    if not sess:
        st.session_state.phase = 'main'
        st.rerun()

    s     = sess.stats()
    carry = sess.last_carryover

    if s['in_loop']:
        st.info(f"🔁 **进入收尾循环** — {len(carry)} 个词将继续出现，直到全部通过")
    else:
        gid = s['gid'] or '（最后）'
        st.info(f"📋 **进入第 {gid} 组** — {len(carry)} 个上组词将随机混入新组")

    st.markdown(f"已通过：**{s['done']}** / {s['total']}")

    if carry:
        st.markdown("**携带词（未完成）：**")
        st.write("　".join(carry))
    else:
        st.success("✅ 上一组词全部通过！")

    if st.button("继续 ▶", type="primary", use_container_width=True):
        st.session_state.phase = 'session'
        _load_audio()
        st.rerun()

    if st.button("⏹ 退出练习", use_container_width=True):
        st.session_state.phase   = 'main'
        st.session_state.session = None
        st.rerun()


# ═══════════════════════════════════════════════════
# 界面：完成
# ═══════════════════════════════════════════════════
def screen_done():
    sess = st.session_state.session
    if not sess:
        st.session_state.phase = 'main'
        st.rerun()

    s = sess.stats()
    st.balloons()
    st.success(f"🎉 练习完成！共 {s['total']} 个词全部短期通过 ✓")

    all_words = sorted(sess.word_map.values(), key=lambda w: -w['long_level'])
    rv_words  = [w['word'] for w in all_words]

    # ── 复习单词 ──────────────────────────────────────
    if rv_words:
        st.subheader("按长期等级顺序复习")
        idx  = max(0, min(st.session_state.rv_idx, len(rv_words) - 1))
        rw   = rv_words[idx]
        rlv  = sess.word_map[rw]['long_level']
        rlbl = {0: "新词", 1: "已掌握", 2: "模糊", 3: "重点"}[rlv]

        st.markdown(f'<div class="word-box">{rw}</div>', unsafe_allow_html=True)
        st.caption(f"长期 {rlv} 级（{rlbl}）— {idx+1} / {len(rv_words)}")

        if st.button("🔊 播放发音", use_container_width=True):
            audio = get_audio(rw, st.session_state.voice, st.session_state.speed)
            render_audio(audio, autoplay=True)

        rc1, rc2 = st.columns(2)
        if rc1.button("◀ 上一个", use_container_width=True):
            if idx > 0:
                st.session_state.rv_idx = idx - 1
                st.rerun()
        if rc2.button("下一个 ▶", use_container_width=True):
            if idx < len(rv_words) - 1:
                st.session_state.rv_idx = idx + 1
                st.rerun()

    st.divider()

    # ── 词汇总览 ──────────────────────────────────────
    st.subheader("词汇总览")
    lv_names = {0: "新词", 1: "已掌握", 2: "模糊", 3: "重点"}
    for lv in [3, 2, 1, 0]:
        ws = [w['word'] for w in all_words if w['long_level'] == lv]
        if ws:
            st.markdown(f"**{lv}级 {lv_names[lv]}（{len(ws)}个）**")
            st.write("　".join(ws))

    st.divider()

    st.download_button(
        "⬇ 导出词库 CSV（含最新长期等级）",
        data=st.session_state.store.export_csv(),
        file_name="japanese_words.csv",
        mime="text/csv",
        type="primary",
        use_container_width=True,
    )

    if st.button("🏠 返回主页", use_container_width=True):
        st.session_state.phase   = 'main'
        st.session_state.session = None
        st.session_state.rv_idx  = 0
        st.rerun()


# ═══════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════
{
    'main':       screen_main,
    'session':    screen_session,
    'group_done': screen_group_done,
    'done':       screen_done,
}.get(st.session_state.phase, screen_main)()
