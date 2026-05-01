# ═══════════════════════════════════════════════════
# 日语变形词汇听力练习  v4.0
# 离线变形库 — 一次生成，永久使用
# Streamlit + edge_tts + GitHub Gist
# ═══════════════════════════════════════════════════
import streamlit as st
import edge_tts
import asyncio, io, random, datetime, json, requests
import pandas as pd

st.set_page_config(
    page_title="日语变形听力", page_icon="🇯🇵",
    layout="centered", initial_sidebar_state="collapsed",
)
st.markdown("""
<style>
  .word-box {
      text-align:center; font-size:56px; font-weight:700;
      letter-spacing:4px; padding:16px 0 10px; line-height:1.15;
  }
  .word-box.hidden { filter:blur(14px); user-select:none; }
  .form-tag {
      display:inline-block; padding:3px 14px; border-radius:20px;
      background:#e8f4fd; color:#1a6fa8; font-size:13px; font-weight:600;
  }
  .meaning-row {
      border-left:3px solid #5ba4d4; padding:6px 10px;
      margin:4px 0; font-size:14px; background:#f7fbff; border-radius:0 6px 6px 0;
  }
  .cov-ok  { color:#2e7d32; font-weight:600; }
  .cov-no  { color:#c62828; }
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
    "🐢 0.75×":"-25%","🐇 0.9×":"-10%",
    "▶ 1.0×":"+0%","⚡ 1.15×":"+15%","🚀 1.3×":"+30%",
}

# ─── 变形类型 ─────────────────────────────────────
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
ALL_FORMS  = VERB_FORMS + ADJ_FORMS
FORM_BY_ID = {f["id"]:f for f in ALL_FORMS}

VERB_KEYS  = {"一段","五段","カ変","サ変","动词","動詞"}
ADJ_KEYS   = {"い形","な形","形容"}
GIST_WORDS = "jp_words.csv"
GIST_CONJ  = "jp_conj.json"
BATCH_SIZE = 50


# ─── 工具 ─────────────────────────────────────────
def _is_verb(t): return any(k in (t or "") for k in VERB_KEYS)
def _is_adj(t):  return any(k in (t or "") for k in ADJ_KEYS)

def applicable_forms(word_entry, enabled_verb, enabled_adj):
    wtype=(word_entry.get("type") or "").strip()
    if _is_adj(wtype):
        return [f for f in ADJ_FORMS  if f["id"] in enabled_adj]
    else:
        # 动词 或 未知词类 → 按动词处理
        # 若词是形容词，请在词汇列表中设置「い形/な形」，形容词变形才会被正确计入覆盖率
        return [f for f in VERB_FORMS if f["id"] in enabled_verb]


# ═══════════════════════════════════════════════════
# WordStore
# ═══════════════════════════════════════════════════
class WordStore:
    def __init__(self): self.words=[]
    def _exists(self): return {w["word"] for w in self.words}
    def _next_grp(self,gs=33): return (len(self.words)//gs)+1
    def _entry(self,word,reading="",wtype="",meaning_zh="",group=None,level=0,gs=33):
        return {"word":word,"reading":reading,"type":wtype,"meaning_zh":meaning_zh,
                "group":group or self._next_grp(gs),"long_level":max(0,min(3,level)),
                "added_date":datetime.date.today().isoformat()}
    def add_text(self,text,gs=33):
        ex=self._exists(); added=0
        for line in text.splitlines():
            w=line.strip()
            if w and w not in ex:
                self.words.append(self._entry(w,gs=gs)); ex.add(w); added+=1
        return added
    def import_csv(self,text,gs=33):
        ex=self._exists(); added=0
        for line in text.splitlines():
            line=line.strip()
            if not line or line.lower().startswith("word"): continue
            p=[x.strip() for x in line.split(",")]
            word=p[0]
            if not word or word in ex: continue
            try:   group=int(p[4]) if len(p)>4 and p[4] else None
            except: group=None
            try:   level=int(p[5]) if len(p)>5 and p[5] else 0
            except: level=0
            self.words.append(self._entry(word,
                p[1] if len(p)>1 else "",p[2] if len(p)>2 else "",
                p[3] if len(p)>3 else "",group,level,gs))
            ex.add(word); added+=1
        return added
    def export_csv(self):
        lines=["word,reading,type,meaning_zh,group,long_level,added_date"]
        for w in self.words:
            lines.append(",".join([w["word"],w.get("reading",""),w.get("type",""),
                w.get("meaning_zh",""),str(w["group"]),str(w["long_level"]),
                w.get("added_date","")]))
        return "\n".join(lines)
    def update_long(self,word,level):
        for w in self.words:
            if w["word"]==word: w["long_level"]=level; break
    def filter(self,levels,groups):
        return [w for w in self.words
                if w["long_level"] in levels and w["group"] in groups]
    def get(self,word):
        for w in self.words:
            if w["word"]==word: return w
        return None


# ═══════════════════════════════════════════════════
# ConjStore  —  变形库
# key = "word::form_id"
# ═══════════════════════════════════════════════════
class ConjStore:
    def __init__(self): self.data={}
    def key(self,word,form_id): return f"{word}::{form_id}"
    def has(self,word,form_id): return self.key(word,form_id) in self.data
    def get(self,word,form_id): return self.data.get(self.key(word,form_id))
    def add(self,word,form_id,conjugated,reading,meanings):
        self.data[self.key(word,form_id)]={"conjugated":conjugated,
                                            "reading":reading,"meanings":meanings}
    def export_json(self):
        return json.dumps(self.data,ensure_ascii=False,indent=2)
    def import_json(self,text):
        d=json.loads(text); added=0
        for k,v in d.items():
            if k not in self.data: self.data[k]=v; added+=1
        return added
    def merge_ai_result(self,json_text):
        text=json_text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data=json.loads(text)
        ok=0; skip=0
        for item in data:
            if item.get("error") or not item.get("conjugated"):
                skip+=1; continue
            word=item.get("word",""); form_id=item.get("form_id","")
            if not word or not form_id: skip+=1; continue
            self.add(word,form_id,item["conjugated"],
                     item.get("reading",""),item.get("meanings",[]))
            ok+=1
        return ok,skip
    def coverage(self,words,enabled_verb,enabled_adj):
        fc={f["id"]:0 for f in ALL_FORMS}
        ft={f["id"]:0 for f in ALL_FORMS}
        missing=[]
        for w in words:
            for f in applicable_forms(w,enabled_verb,enabled_adj):
                ft[f["id"]]=ft.get(f["id"],0)+1
                if self.has(w["word"],f["id"]):
                    fc[f["id"]]=fc.get(f["id"],0)+1
                else:
                    missing.append((w,f))
        return fc,ft,missing
    def build_practice_items(self,words,enabled_verb,enabled_adj,forms_per_word=0):
        """forms_per_word=0 -> 全量；>0 -> 每词按权重随机抽 K 个变形"""
        items=[]
        for w in words:
            candidates=[]
            for f in applicable_forms(w,enabled_verb,enabled_adj):
                c=self.get(w["word"],f["id"])
                if c:
                    candidates.append((f,c))
            if not candidates: continue
            if forms_per_word>0 and forms_per_word<len(candidates):
                pool=list(range(len(candidates)))
                pool_w=[f["weight"] for f,_ in candidates]
                k=min(forms_per_word,len(candidates))
                chosen_idx=[]
                for _ in range(k):
                    total_w=sum(pool_w)
                    r=random.uniform(0,total_w); acc=0
                    for ii,pw in enumerate(pool_w):
                        acc+=pw
                        if r<=acc:
                            chosen_idx.append(pool[ii])
                            pool_w.pop(ii); pool.pop(ii); break
                chosen=[candidates[i] for i in chosen_idx]
            else:
                chosen=candidates
            for f,c in chosen:
                items.append({"word":w["word"],"reading":w.get("reading",""),
                    "type":w.get("type",""),"meaning_zh":w.get("meaning_zh",""),
                    "form_id":f["id"],"form_label":f["label"],"form_weight":f["weight"],
                    "conjugated":c["conjugated"],"conj_reading":c["reading"],
                    "meanings":c["meanings"]})
        return items


# ═══════════════════════════════════════════════════
# 提示词生成
# ═══════════════════════════════════════════════════
def make_prompt(batch):
    lines=[]
    for w,f in batch:
        r=w.get("reading","") or "—"
        tp=w.get("type","")   or "未知"
        lines.append(f"{w['word']} | {r} | {tp} | {f['label']} | {f['id']}")
    word_table="\n".join(lines)
    return f"""你是日语语法教师助手。请将下列词汇按指定变形类型变形，返回 JSON 数组。
只返回 JSON，不要任何解释或 markdown 符号（不要 ``` ）。

每个元素格式：
{{
  "word": "原词基本形（原样返回）",
  "form_id": "变形ID（原样返回）",
  "conjugated": "变形后的词",
  "reading": "变形后完整读法（全平假名）",
  "meanings": [
    "「使用场景」：中文说明（15字以内）",
    "「使用场景」：中文说明"
  ]
}}

meanings：列出 2～4 条该变形最典型用法，每条注明场景（连续动作/请求/原因/条件/否定等）用中文。
若该词类完全不支持此变形，加 "error":"不支持" 字段，conjugated 留空。

---
词汇列表（原词 | 读法 | 词类 | 变形类型 | form_id）：
{word_table}
---

请返回包含以上全部 {len(batch)} 个词的 JSON 数组："""


# ═══════════════════════════════════════════════════
# PracticeSession
# ═══════════════════════════════════════════════════
class PracticeSession:
    def __init__(self,items):
        self.items=items; self.total=len(items); self.passed=set()
        weights=[it["form_weight"] for it in items]
        pop=list(range(self.total))
        self.queue=random.choices(pop,weights=weights,k=self.total*2)
        self.q_pos=0
    def _advance(self):
        while self.q_pos<len(self.queue):
            if self.queue[self.q_pos] not in self.passed: return
            self.q_pos+=1
        undone=[i for i in range(self.total) if i not in self.passed]
        if not undone: return
        weights=[self.items[i]["form_weight"] for i in undone]
        self.queue.extend(random.choices(undone,weights=weights,k=len(undone)*2))
    def current(self):
        self._advance()
        if self.q_pos>=len(self.queue): return None,-1
        idx=self.queue[self.q_pos]
        return self.items[idx],idx
    def rate(self,lv):
        _,idx=self.current()
        if idx<0: return "done"
        if lv==1: self.passed.add(idx)
        else:
            ins=self.q_pos+1+(3 if lv==2 else 1)
            self.queue.insert(min(ins,len(self.queue)),idx)
        self.q_pos+=1
        if len(self.passed)==self.total: return "done"
        return "ok"
    def prev(self):
        if self.q_pos>0: self.q_pos-=1; return True
        return False
    def stats(self):
        return {"done":len(self.passed),"total":self.total,
                "queue_rem":max(0,len(self.queue)-self.q_pos)}


# ═══════════════════════════════════════════════════
# GitHub Gist
# ═══════════════════════════════════════════════════
def _gist_cfg():
    try:
        t=st.secrets["github"]["token"]
        g=st.secrets["github"].get("gist_id","")
        return t,g or None
    except: return None,None

def _gist_enabled(): return bool(_gist_cfg()[0])

def _gh(method,url,**kw):
    t,_=_gist_cfg()
    return requests.request(method,url,timeout=15,
        headers={"Authorization":f"token {t}",
                 "Accept":"application/vnd.github+json"},**kw)

def _gist_find():
    p=1
    while True:
        items=_gh("GET","https://api.github.com/gists",
                  params={"per_page":100,"page":p}).json()
        if not items: return None
        for i in items:
            if GIST_WORDS in i.get("files",{}): return i["id"]
        p+=1

def _raw(gist_data,filename):
    f=gist_data.get("files",{}).get(filename)
    if not f: return None
    return requests.get(f["raw_url"],timeout=15).text

def do_gist_load():
    _,gid=_gist_cfg()
    with st.spinner("☁️ 从 GitHub Gist 加载…"):
        try:
            gid=gid or _gist_find()
            if not gid: st.warning("未找到 Gist，请先保存一次"); return
            gist=_gh("GET",f"https://api.github.com/gists/{gid}").json()
            words_csv=_raw(gist,GIST_WORDS)
            conj_json=_raw(gist,GIST_CONJ)
        except Exception as e: st.error(f"加载失败：{e}"); return
    n_w=st.session_state.store.import_csv(words_csv) if words_csv else 0
    n_c=st.session_state.conj_store.import_json(conj_json) if conj_json else 0
    st.session_state.gist_id=gid
    st.session_state.gist_last_sync=datetime.datetime.now().strftime("%H:%M:%S")
    st.success(f"✅ 词库 +{n_w} 词 / 变形库 +{n_c} 条"); st.rerun()

def do_gist_save():
    store=st.session_state.store; cs=st.session_state.conj_store
    if not store.words: st.warning("词库为空"); return
    _,cfg_gid=_gist_cfg(); gid=st.session_state.get("gist_id") or cfg_gid
    with st.spinner("☁️ 保存到 GitHub Gist…"):
        try:
            gid=gid or _gist_find()
            payload={"description":"日语变形听力练习数据",
                     "files":{GIST_WORDS:{"content":store.export_csv()},
                              GIST_CONJ: {"content":cs.export_json()}}}
            if gid:
                new_id=_gh("PATCH",f"https://api.github.com/gists/{gid}",json=payload).json()["id"]
            else:
                payload["public"]=False
                new_id=_gh("POST","https://api.github.com/gists",json=payload).json()["id"]
        except Exception as e: st.error(f"保存失败：{e}"); return
    st.session_state.gist_id=new_id
    st.session_state.gist_last_sync=datetime.datetime.now().strftime("%H:%M:%S")
    st.success(f"✅ 已保存（词库 {len(store.words)} 词 / 变形库 {len(cs.data)} 条）")
    if not gid: st.info(f"新建 Gist ID：`{new_id}`")


# ═══════════════════════════════════════════════════
# 音频
# ═══════════════════════════════════════════════════
def get_audio(text, voice, rate="+0%"):
    """
    在独立线程中创建并关闭 event loop，避免 Streamlit 多次重跑
    时泄漏 loop，防止移动端内存耗尽导致闪退。
    """
    async def _gen():
        comm = edge_tts.Communicate(text, voice, rate=rate)
        buf = io.BytesIO()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        return buf.read()

    import threading
    result = [None]

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result[0] = loop.run_until_complete(_gen())
        except Exception:
            result[0] = None
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=30)
    return result[0]


# ═══════════════════════════════════════════════════
# session_state 初始化
# ═══════════════════════════════════════════════════
def _init():
    defaults={
        "phase":"main","store":WordStore(),"conj_store":ConjStore(),
        "session":None,"voice":"ja-JP-NanamiNeural","speed":"+0%",
        "gist_id":None,"gist_last_sync":None,
        "cur_audio":None,"last_audio_key":"","autoplay":False,"show_answer":False,
        "last_imported_file":"",
        "enabled_verb":{"te","past","nai","masu","potential","passive","causative","ba"},
        "enabled_adj":{"adj_neg","adj_past","adj_adv","adj_te"},
        "gen_batches":[],"gen_batch_idx":0,
        "sim_session":None,"sim_chosen":None,
    }
    for k,v in defaults.items():
        if k not in st.session_state: st.session_state[k]=v

_init()


# ═══════════════════════════════════════════════════
# 主页
# ═══════════════════════════════════════════════════
def screen_main():
    store=st.session_state.store
    cs=st.session_state.conj_store
    ev=st.session_state.enabled_verb
    ea=st.session_state.enabled_adj

    st.title("🇯🇵 日语变形听力练习")

    # Gist
    with st.expander("☁️ GitHub Gist 同步",expanded=False):
        if _gist_enabled():
            c1,c2=st.columns(2)
            with c1:
                if st.button("📥 从 Gist 加载",use_container_width=True): do_gist_load()
            with c2:
                if st.button("📤 保存到 Gist",use_container_width=True): do_gist_save()
            if st.session_state.gist_last_sync:
                st.caption(f"上次同步：{st.session_state.gist_last_sync}")
        else:
            st.caption("在 secrets.toml 配置 `[github] token` 后可使用云同步")

    # 词库
    with st.expander("📚 词库管理",expanded=not bool(store.words)):
        st.caption("CSV：`word,reading,type,meaning_zh`（后三列可省略，AI 会判断词类）")
        tab_csv,tab_txt=st.tabs(["上传 CSV","粘贴纯文本"])
        with tab_csv:
            f=st.file_uploader("CSV",type="csv",label_visibility="collapsed")
            if f is not None:
                fkey=f"{f.name}_{f.size}"
                if fkey!=st.session_state.get("last_imported_file"):
                    n=store.import_csv(f.read().decode("utf-8"))
                    st.session_state.last_imported_file=fkey
                    st.success(f"✅ 导入 {n} 个词"); st.rerun()
        with tab_txt:
            txt=st.text_area("每行一个基本形",height=100,label_visibility="collapsed")
            if st.button("添加",use_container_width=True):
                n=store.add_text(txt); st.success(f"✅ 添加 {n} 个词"); st.rerun()
        if store.words:
            c1,c2=st.columns(2)
            with c1:
                st.download_button("⬇ 下载词库",data=store.export_csv(),
                    file_name="jp_words.csv",mime="text/csv",use_container_width=True)
            with c2:
                if st.button("🗑 清空词库",use_container_width=True):
                    st.session_state.store=WordStore(); st.rerun()

    if not store.words:
        st.info("👆 请先导入词库"); return

    st.markdown(f"词库共 **{len(store.words)}** 个词")

    # 词汇列表（可直接编辑词类与长期等级）
    with st.expander(f"📋 词汇列表（{len(store.words)} 个词）", expanded=False):
        df = pd.DataFrame([{
            "单词":     w["word"],
            "読み":     w.get("reading",""),
            "词类":     w.get("type",""),
            "中文意思": w.get("meaning_zh",""),
            "分组":     int(w["group"]),
            "长期等级": int(w["long_level"]),
        } for w in store.words])

        edited = st.data_editor(
            df,
            column_config={
                "单词":     st.column_config.TextColumn("单词",   disabled=True, width="small"),
                "読み":     st.column_config.TextColumn("読み",   width="small"),
                "词类":     st.column_config.SelectboxColumn(
                    "词类", width="small",
                    options=["","一段","五段","カ変","サ変","い形","な形"],
                    help="动词：一段/五段/カ変/サ変　形容词：い形/な形"),
                "中文意思": st.column_config.TextColumn("中文",   width="medium"),
                "分组":     st.column_config.NumberColumn("组",   min_value=1, step=1, width="small"),
                "长期等级": st.column_config.SelectboxColumn(
                    "等级", width="small",
                    options=[0,1,2,3],
                    help="0=新词  1=已掌握  2=模糊  3=重点"),
            },
            use_container_width=True,
            height=min(420, 44+36*len(store.words)),
            key="word_list_editor",
            hide_index=False,
        )

        if st.button("💾 保存词汇修改", use_container_width=True, key="save_word_edits"):
            changed=0
            for i, row in edited.iterrows():
                if i >= len(store.words): break
                w=store.words[i]
                nr = str(row["読み"])     if pd.notna(row["読み"])     else ""
                nt = str(row["词类"])     if pd.notna(row["词类"])     else ""
                nm = str(row["中文意思"]) if pd.notna(row["中文意思"]) else ""
                ng = int(row["分组"])     if pd.notna(row["分组"])     else w["group"]
                nl = int(row["长期等级"]) if pd.notna(row["长期等级"]) else w["long_level"]
                if (w.get("reading","")!=nr or w.get("type","")!=nt or
                        w.get("meaning_zh","")!=nm or w["group"]!=ng or w["long_level"]!=nl):
                    w["reading"]=nr; w["type"]=nt; w["meaning_zh"]=nm
                    w["group"]=ng; w["long_level"]=nl; changed+=1
            if changed:
                st.success(f"✅ 已更新 {changed} 个词"); st.rerun()
            else:
                st.info("无变化")

    # 变形类型设置（在覆盖率之前，因为覆盖率依赖它）
    with st.expander("⚙️ 变形类型设置",expanded=False):
        st.caption("**动词变形**（★★★=主要权重×3，★=次要权重×1）")
        ev2=set(ev)
        cols=st.columns(4)
        for i,f in enumerate(VERB_FORMS):
            star="★★★" if f["weight"]==3 else "★"
            if cols[i%4].checkbox(f"{star} {f['label']}",value=f["id"] in ev2,key=f"vf_{f['id']}"):
                ev2.add(f["id"])
            else: ev2.discard(f["id"])
        st.session_state.enabled_verb=ev2 or {"te"}

        st.caption("**形容词变形**")
        ea2=set(ea)
        cols2=st.columns(4)
        for i,f in enumerate(ADJ_FORMS):
            if cols2[i%4].checkbox(f["label"],value=f["id"] in ea2,key=f"af_{f['id']}"):
                ea2.add(f["id"])
            else: ea2.discard(f["id"])
        st.session_state.enabled_adj=ea2 or {"adj_neg"}
        ev=st.session_state.enabled_verb
        ea=st.session_state.enabled_adj

    # 覆盖率
    with st.expander("📊 变形库覆盖率",expanded=True):
        fc,ft,missing=cs.coverage(store.words,ev,ea)
        total_pairs=sum(ft.values())
        total_have =sum(fc.values())
        pct=int(100*total_have/total_pairs) if total_pairs else 0
        st.progress(pct/100,
            text=f"整体覆盖 {total_have} / {total_pairs} 条（{pct}%）")

        # 统计词类分布
        n_verb=sum(1 for w in store.words if _is_verb((w.get("type") or "").strip()))
        n_adj =sum(1 for w in store.words if _is_adj((w.get("type") or "").strip()))
        n_unk =len(store.words)-n_verb-n_adj

        vcol,acol=st.columns(2)
        with vcol:
            st.caption(f"**動詞変形** · {n_verb} 动词 + {n_unk} 未知")
            sub=st.columns(2); vi=0
            for f in VERB_FORMS:
                fid=f["id"]
                if ft.get(fid,0)==0: continue
                have=fc.get(fid,0); need=ft[fid]
                cls="cov-ok" if have==need else "cov-no"
                sub[vi%2].markdown(
                    f"<span class='{cls}'>{f['label']}</span><br><small>{have}/{need}</small>",
                    unsafe_allow_html=True); vi+=1
        with acol:
            st.caption(f"**形容詞変形** · {n_adj} 形容词")
            if n_adj==0:
                st.caption("（词库中无形容词，或词类未设置）")
            else:
                sub2=st.columns(2); ai=0
                for f in ADJ_FORMS:
                    fid=f["id"]
                    if ft.get(fid,0)==0: continue
                    have=fc.get(fid,0); need=ft[fid]
                    cls="cov-ok" if have==need else "cov-no"
                    sub2[ai%2].markdown(
                        f"<span class='{cls}'>{f['label']}</span><br><small>{have}/{need}</small>",
                        unsafe_allow_html=True); ai+=1

        if n_unk>0:
            st.info(f"ℹ️ {n_unk} 个词类型未知，已默认按**动词**计算覆盖率。"
                    f"若其中有形容词，请在「📋 词汇列表」中将词类设为「い形」或「な形」。")

        st.divider()
        if missing:
            st.warning(f"⚠️ 还有 **{len(missing)}** 个词×变形 缺少数据 "
                       f"（约需 {-(-len(missing)//BATCH_SIZE)} 批提示词）")
            c1,c2=st.columns(2)
            with c1:
                if st.button("📝 生成补全提示词",type="primary",use_container_width=True):
                    batches=[]
                    for i in range(0,len(missing),BATCH_SIZE):
                        b=missing[i:i+BATCH_SIZE]
                        batches.append((i//BATCH_SIZE+1,make_prompt(b),b))
                    st.session_state.gen_batches=batches
                    st.session_state.gen_batch_idx=0
                    st.session_state.phase="gen"; st.rerun()
            with c2:
                # 导入已有 JSON（手动上传）
                conj_file=st.file_uploader("或上传变形库 JSON",
                    type="json",label_visibility="collapsed",key="conj_upload")
                if conj_file:
                    fkey2=f"conj_{conj_file.name}_{conj_file.size}"
                    if fkey2!=st.session_state.get("last_conj_file"):
                        n=cs.import_json(conj_file.read().decode("utf-8"))
                        st.session_state.last_conj_file=fkey2
                        st.success(f"✅ 导入变形库 {n} 条"); st.rerun()
        else:
            st.success("✅ 所有变形数据均已就绪！")

        if cs.data:
            st.download_button("⬇ 下载变形库 JSON",data=cs.export_json(),
                file_name="jp_conj.json",mime="application/json",
                use_container_width=True)

    st.divider()

    # 筛选 & 开始
    groups={}
    for w in store.words: groups.setdefault(w["group"],[]).append(w)
    lv_map={0:"0 新词",1:"1 已掌握",2:"2 模糊",3:"3 重点"}
    lv_sel=st.multiselect("长期等级",options=[0,1,2,3],default=[0,2,3],
                          format_func=lambda x:lv_map[x])
    gr_sel=st.multiselect("分组",options=sorted(groups),default=sorted(groups),
        format_func=lambda x:f"第 {x} 组（{len(groups[x])} 词）",
        label_visibility="collapsed")

    ws=store.filter(lv_sel,gr_sel)
    voice_name=st.selectbox("语音",list(VOICES.keys()))

    # 每词变形数设置
    max_verb_forms=len([f for f in VERB_FORMS if f["id"] in ev])
    max_adj_forms =len([f for f in ADJ_FORMS  if f["id"] in ea])
    max_forms=max(max_verb_forms,max_adj_forms,1)
    st.markdown("**每词练习变形数**")
    c_sl,c_info=st.columns([3,1])
    with c_sl:
        fpw=st.slider("每词变形数",min_value=1,max_value=max_forms,
            value=min(st.session_state.get("forms_per_word",2),max_forms),
            label_visibility="collapsed",key="fpw_slider")
    st.session_state.forms_per_word=fpw
    with c_info:
        if fpw>=max_forms:
            st.caption("全量模式")
        else:
            st.caption(f"{fpw}/{max_forms} 个")

    # 全量 or 抽样
    fpw_actual=0 if fpw>=max_forms else fpw
    items=cs.build_practice_items(ws,ev,ea,fpw_actual)

    if items:
        avg_forms=len(items)/len(ws) if ws else 0
        st.info(f"🎯 **{len(ws)}** 词 × 平均 **{avg_forms:.1f}** 变形 = **{len(items)}** 条目")
    elif ws:
        st.warning("⚠️ 筛选词还没有变形数据，请先生成提示词")
    else:
        st.warning("⚠️ 无词匹配，请调整筛选条件")

    if st.button("🎧 开始练习",type="primary",
                 disabled=(not items),use_container_width=True):
        st.session_state.voice=VOICES[voice_name]
        # 开始时重新抽样（每次开始结果不同）
        st.session_state.session=PracticeSession(
            cs.build_practice_items(ws,ev,ea,fpw_actual))
        st.session_state.show_answer=False
        st.session_state.last_audio_key=""
        st.session_state.phase="session"; st.rerun()

    # 相似音辨别练习入口
    sim_items=[it for it in cs.build_practice_items(ws,ev,ea,0)
               if it.get("conj_reading")]
    sim_pool=build_similarity_pool(sim_items)
    sim_q_count=sum(len(g) for g in sim_pool.values())
    sim_disabled=(sim_q_count<2)
    sim_tip=(f"🔀 相似音辨别练习（{sim_q_count} 题）"
             if not sim_disabled else "🔀 相似音练习（需至少2个有读音的相近词）")
    if st.button(sim_tip,disabled=sim_disabled,use_container_width=True):
        st.session_state.voice=VOICES[voice_name]
        st.session_state.sim_session=SimilaritySession(sim_items)
        st.session_state.sim_chosen=None
        st.session_state.last_audio_key=""
        st.session_state.phase="similarity"; st.rerun()



# ═══════════════════════════════════════════════════
# 相似音辨别练习  —  工具 & 会话
# ═══════════════════════════════════════════════════
def _conj_reading_norm(it):
    """取变形后的规范读音（优先 conj_reading，退回 conjugated 字面）"""
    return (it.get("conj_reading") or it.get("conjugated","")).strip()

def build_similarity_pool(items, prefix_len=3):
    """
    正确的聚类维度：(form_id, 变形读音前 prefix_len 字)

    逻辑：同一变形类型下，变形后读音的前几个假名相同的词，
    在听力上最容易混淆，需要放在一起练习辨别。

    举例（prefix_len=3）：
      あう → て形 → あって  → key=(te, "あっ")  ┐
      ある → て形 → あって  → key=(te, "あっ")  ┘ 同组，完全相同！

      いく → て形 → いって  → key=(te, "いっ")  ┐
      いう → て形 → いって  → key=(te, "いっ")  ┘ 同组

      かう → て形 → かって  → key=(te, "かっ")  ┐
      かつ → て形 → かって  → key=(te, "かっ")  ┘ 同组

    只保留同组原词 ≥ 2 个的桶（有辨别价值）。
    返回：{(fid, prefix): [item, ...]}
    """
    from collections import defaultdict
    buckets=defaultdict(list)
    for it in items:
        r=_conj_reading_norm(it)
        fid=it.get("form_id","")
        prefix=r[:prefix_len] if len(r)>=prefix_len else r
        buckets[(fid, prefix)].append(it)
    return {k:v for k,v in buckets.items()
            if len({i["word"] for i in v})>=2}


class SimilaritySession:
    """
    听音 → 从选项中选出是哪个原词的变形。

    选项构成（按优先级）：
      ① 同混淆组的其他词（最高优先，这才是真正需要辨别的）
      ② 同 form_id 但读音不同的词（次要干扰，保持变形类型一致）
    答案确认（confirm）之后才推进，便于展示学习反馈。
    """
    def __init__(self, items, choices_n=4, prefix_len=3):
        self.all_items=items
        self.choices_n=choices_n
        self.prefix_len=prefix_len
        self.pool=build_similarity_pool(items, prefix_len)
        self.questions=self._make_questions()
        random.shuffle(self.questions)
        self.q_pos=0
        self.correct=0
        self.total=len(self.questions)

    def _make_questions(self):
        qs=[]
        # 按 form_id 预先索引，供补充干扰项用
        by_form={}
        for it in self.all_items:
            by_form.setdefault(it.get("form_id",""),[]).append(it)

        for (fid, prefix), group in self.pool.items():
            # 同组所有的原词（混淆核心）
            group_words={it["word"] for it in group}

            for target in group:
                # ① 同混淆组的干扰（不同词，任意变形记录均可）
                confused=[it for it in group if it["word"]!=target["word"]]

                # ② 补充：同 form_id 的其他词（读音不在同一混淆桶）
                extra=[it for it in by_form.get(fid,[])
                       if it["word"] not in group_words]
                random.shuffle(extra)

                all_dist=confused+extra
                chosen_dist=all_dist[:self.choices_n-1]
                if not chosen_dist:
                    continue

                choices=chosen_dist+[target]
                random.shuffle(choices)
                qs.append({
                    "target":       target,
                    "choices":      choices,
                    "correct_idx":  choices.index(target),
                    "fid":          fid,
                    "prefix":       prefix,
                    # 保存整组混淆词，供答题后显示学习提示
                    "confusion_group": list(group),
                })
        return qs

    def current(self):
        if self.q_pos>=self.total: return None
        return self.questions[self.q_pos]

    def confirm(self, chosen_idx):
        q=self.current()
        if q is None: return "done"
        if chosen_idx==q["correct_idx"]: self.correct+=1
        self.q_pos+=1
        return "done" if self.q_pos>=self.total else "ok"

    def stats(self):
        return {"done":self.q_pos,"total":self.total,"correct":self.correct}


# ═══════════════════════════════════════════════════
# 相似音练习界面
# ═══════════════════════════════════════════════════
def screen_similarity_session():
    sess=st.session_state.get("sim_session")
    if not sess: st.session_state.phase="main"; st.rerun(); return

    q=sess.current()
    if q is None: st.session_state.phase="sim_done"; st.rerun(); return

    target=q["target"]
    fid=q["fid"]
    form_label=target["form_label"]

    audio_key=f"sim::{target['word']}::{fid}::{st.session_state.speed}"
    if st.session_state.last_audio_key!=audio_key:
        with st.spinner("🎵 生成音频…"):
            st.session_state.cur_audio=get_audio(
                target["conjugated"],st.session_state.voice,st.session_state.speed)
        st.session_state.last_audio_key=audio_key
        st.session_state.autoplay=True
        st.session_state.sim_chosen=None

    s=sess.stats()
    label=f"题目 **{s['done']+1}/{s['total']}**"
    if s["done"]>0:
        pct=int(100*s["correct"]/s["done"])
        label+=f"  ·  正确 {s['correct']}/{s['done']}（{pct}%）"
    st.caption(label)
    st.progress(s["done"]/max(s["total"],1))

    # 题目说明：强调这是哪类变形的听辨
    conj_reading=_conj_reading_norm(target)
    st.markdown(
        f"<div style='text-align:center;margin:8px 0'>"
        f"<span class='form-tag'>{form_label}</span>"
        f"&nbsp;&nbsp;听到的是 <b>{conj_reading}</b>，请选出对应的原词</div>",
        unsafe_allow_html=True)

    autoplay=st.session_state.get("autoplay",False)
    st.session_state.autoplay=False
    if st.session_state.cur_audio:
        st.audio(st.session_state.cur_audio,format="audio/mpeg",autoplay=autoplay)

    col_spd,col_rp=st.columns([4,1])
    with col_spd:
        spd_name=st.selectbox("速度",list(SPEEDS.keys()),
            index=list(SPEEDS.values()).index(st.session_state.speed),
            label_visibility="collapsed",key="sim_spd")
        new_speed=SPEEDS[spd_name]
        if new_speed!=st.session_state.speed:
            st.session_state.speed=new_speed
            st.session_state.last_audio_key=""; st.rerun()
    with col_rp:
        if st.button("🔊",use_container_width=True,key="sim_rp"):
            st.session_state.last_audio_key=""; st.rerun()

    st.divider()

    chosen=st.session_state.get("sim_chosen")  # None = 未作答

    if chosen is None:
        # ── 作答阶段：选项显示原词 + 读み ──────────────
        st.markdown("**这个音是哪个词的变形？**")
        cols=st.columns(2)
        for i,ch in enumerate(q["choices"]):
            word=ch["word"]
            rdg=ch.get("reading","")
            meaning=ch.get("meaning_zh","")
            lbl=word
            if rdg:     lbl+=f"\n{rdg}"
            if meaning: lbl+=f"\n{meaning}"
            with cols[i%2]:
                if st.button(lbl,key=f"sim_c_{i}",use_container_width=True):
                    st.session_state.sim_chosen=i; st.rerun()
    else:
        # ── 反馈阶段 ──────────────────────────────────
        is_correct=(chosen==q["correct_idx"])
        tgt=q["choices"][q["correct_idx"]]

        if is_correct:
            st.success(f"✅ 正确！**{tgt['word']}** → {tgt.get('conjugated','')}（{conj_reading}）")
        else:
            chosen_word=q["choices"][chosen]["word"]
            st.error(f"❌ 你选了 **{chosen_word}**，正确答案是 **{tgt['word']}**"
                     f" → {tgt.get('conjugated','')}（{conj_reading}）")

        # 混淆组说明：列出所有在该变形下听起来相同/相近的词
        cgroup=q.get("confusion_group",[])
        if len(cgroup)>=2:
            entries=[]
            for it in cgroup:
                r=_conj_reading_norm(it)
                entries.append(f"**{it['word']}**（{it.get('reading','') or '?'}）→ {it['conjugated']}（{r}）")
            st.info("⚠️ 这些词在 **{}** 下听起来相同或极像，需结合语境辨别：\n\n{}".format(
                form_label, "　/　".join(entries)))

        if st.button("▶ 下一题",type="primary",use_container_width=True,key="sim_next"):
            result=sess.confirm(chosen)
            st.session_state.sim_chosen=None
            st.session_state.last_audio_key=""
            if result=="done": st.session_state.phase="sim_done"
            st.rerun()

    if st.button("⏹ 退出",use_container_width=True,key="sim_exit"):
        st.session_state.phase="main"; st.session_state.sim_session=None; st.rerun()


def screen_sim_done():
    sess=st.session_state.get("sim_session")
    if not sess: st.session_state.phase="main"; st.rerun(); return
    s=sess.stats()
    pct=int(100*s["correct"]/max(s["total"],1))
    st.balloons()
    st.success(f"🎉 相似音练习完成！{s['correct']}/{s['total']} 题正确（{pct}%）")
    emoji="🏆" if pct>=90 else ("👍" if pct>=70 else "📖")
    st.markdown(f"### {emoji} 得分率 {pct}%")
    if st.button("🔁 再来一次",type="primary",use_container_width=True):
        pool=build_similarity_pool(
            [it for it in (sess.all_items or []) if it.get("conj_reading")])
        if pool:
            st.session_state.sim_session=SimilaritySession(sess.all_items)
            st.session_state.sim_chosen=None
            st.session_state.last_audio_key=""
            st.session_state.phase="similarity"; st.rerun()
    if st.button("🏠 返回主页",use_container_width=True):
        st.session_state.phase="main"; st.session_state.sim_session=None; st.rerun()



    batches=st.session_state.gen_batches
    if not batches: st.session_state.phase="main"; st.rerun(); return

    total=len(batches)
    bidx=st.session_state.gen_batch_idx
    batch_no,prompt,missing_list=batches[bidx]

    st.title("📝 批量生成变形数据")

    # 总体进度条
    done_batches=sum(1 for b in batches[:bidx])
    st.progress(done_batches/total,
        text=f"进度：{done_batches}/{total} 批已完成")

    # 批次导航
    cols=st.columns(len(batches) if len(batches)<=10 else 10)
    for i,(bn,_,ml) in enumerate(batches[:10]):
        label=f"{'✅' if i<bidx else ('▶' if i==bidx else '○')} {bn}"
        if cols[i].button(label,key=f"bsel_{i}",use_container_width=True):
            st.session_state.gen_batch_idx=i; st.rerun()
    if len(batches)>10:
        st.caption(f"共 {total} 批，仅显示前10个导航")

    st.markdown(f"#### 第 {batch_no} 批 — {len(missing_list)} 个词×变形")
    st.divider()

    # 步骤 1
    st.markdown("**① 复制提示词** → 粘贴给 AI（Claude / ChatGPT 均可）")
    st.text_area("提示词",value=prompt,height=280,
                 key=f"pt_{bidx}",label_visibility="collapsed")

    st.divider()

    # 步骤 2
    st.markdown("**② 将 AI 返回的 JSON 粘贴到这里**")
    ai_result=st.text_area("AI 结果",height=220,
        placeholder='[\n  {"word":"食べる","form_id":"te","conjugated":"食べて",...},\n  ...\n]',
        key=f"res_{bidx}",label_visibility="collapsed")

    if st.button("✅ 合并到变形库",type="primary",use_container_width=True):
        if not ai_result.strip():
            st.warning("请先粘贴 AI 返回的 JSON")
        else:
            try:
                ok,skip=st.session_state.conj_store.merge_ai_result(ai_result)
                st.success(f"✅ 合并 {ok} 条，跳过 {skip} 条（不支持/格式错误）")
                if bidx+1<total:
                    st.session_state.gen_batch_idx=bidx+1; st.rerun()
                else:
                    st.balloons(); st.success("🎉 所有批次完成！")
                    if _gist_enabled(): do_gist_save()
                    st.session_state.gen_batches=[]
                    st.session_state.gen_batch_idx=0
                    st.session_state.phase="main"; st.rerun()
            except Exception as e:
                st.error(f"JSON 解析失败：{e}\n\n请确认 AI 返回的是纯 JSON 数组")

    st.divider()
    c1,c2,c3=st.columns(3)
    with c1:
        if bidx>0:
            if st.button("◀ 上一批",use_container_width=True):
                st.session_state.gen_batch_idx=bidx-1; st.rerun()
    with c2:
        if bidx+1<total:
            if st.button("跳过 ▶",use_container_width=True):
                st.session_state.gen_batch_idx=bidx+1; st.rerun()
    with c3:
        if st.button("⏹ 退出",use_container_width=True):
            st.session_state.phase="main"
            st.session_state.gen_batches=[]; st.rerun()


# ═══════════════════════════════════════════════════
# 练习界面
# ═══════════════════════════════════════════════════
def screen_session():
    sess=st.session_state.session
    if not sess: st.session_state.phase="main"; st.rerun(); return

    item,idx=sess.current()
    if item is None: st.session_state.phase="done"; st.rerun(); return

    audio_key=f"{item['word']}::{item['form_id']}::{st.session_state.speed}"
    if st.session_state.last_audio_key!=audio_key:
        with st.spinner("🎵 生成音频…"):
            st.session_state.cur_audio=get_audio(
                item["conjugated"],st.session_state.voice,st.session_state.speed)
        st.session_state.last_audio_key=audio_key
        st.session_state.show_answer=False
        st.session_state.autoplay=True

    s=sess.stats()
    st.caption(f"已通过 **{s['done']}/{s['total']}** · 队列剩余 {s['queue_rem']}")
    st.progress(s["done"]/max(s["total"],1))

    st.markdown(
        f"<div style='text-align:center;margin-bottom:6px'>"
        f"<span class='form-tag'>{item['form_label']}</span></div>",
        unsafe_allow_html=True)

    show=st.session_state.get("show_answer",False)
    cls="" if show else " hidden"
    st.markdown(f"<div class='word-box{cls}'>{item['conjugated']}</div>",
                unsafe_allow_html=True)

    autoplay=st.session_state.get("autoplay",False)
    st.session_state.autoplay=False
    if st.session_state.cur_audio:
        st.audio(st.session_state.cur_audio,format="audio/mpeg",autoplay=autoplay)

    col_spd,col_rp=st.columns([4,1])
    with col_spd:
        spd_name=st.selectbox("速度",list(SPEEDS.keys()),
            index=list(SPEEDS.values()).index(st.session_state.speed),
            label_visibility="collapsed")
        new_speed=SPEEDS[spd_name]
        if new_speed!=st.session_state.speed:
            st.session_state.speed=new_speed
            st.session_state.last_audio_key=""  # 速度变化强制重新生成音频
            st.rerun()
    with col_rp:
        if st.button("🔊",use_container_width=True):
            st.session_state.last_audio_key=""; st.rerun()

    st.divider()

    if st.toggle("👁 显示答案",value=show,key="show_answer"):
        c1,c2=st.columns(2)
        with c1:
            st.markdown("**基本形**")
            st.markdown(f"#### {item['word']}")
            if item.get("reading"):    st.caption(f"読み：{item['reading']}")
            if item.get("meaning_zh"): st.caption(f"🈶 {item['meaning_zh']}")
            if item.get("type"):       st.caption(f"词类：{item['type']}")
        with c2:
            st.markdown(f"**{item['form_label']}**")
            st.markdown(f"#### {item['conjugated']}")
            if item.get("conj_reading"): st.caption(f"読み：{item['conj_reading']}")
        if item.get("meanings"):
            st.markdown("**变形用法**")
            for m in item["meanings"]:
                st.markdown(f"<div class='meaning-row'>・{m}</div>",
                            unsafe_allow_html=True)

    st.divider()
    st.caption("评级 → 自动跳下一词")

    def do_rate(lv):
        r=sess.rate(lv)
        st.session_state.last_audio_key=""
        if r=="done": st.session_state.phase="done"
        st.rerun()

    b1,b2,b3=st.columns(3)
    with b1:
        if st.button("① 听懂了",use_container_width=True,type="secondary"): do_rate(1)
    with b2:
        if st.button("② 不确定",use_container_width=True): do_rate(2)
    with b3:
        if st.button("③ 没听懂",use_container_width=True,type="primary"): do_rate(3)

    n1,_,n3=st.columns(3)
    with n1:
        if st.button("◀ 上一",use_container_width=True):
            if sess.prev(): st.session_state.last_audio_key=""; st.rerun()
    with n3:
        if st.button("⏹ 退出",use_container_width=True):
            st.session_state.phase="main"; st.session_state.session=None; st.rerun()

    we=st.session_state.store.get(item["word"]) or {}
    cur_lv=we.get("long_level",0) if isinstance(we,dict) else 0
    lv_names={0:"0 新词",1:"1 掌握",2:"2 模糊",3:"3 重点"}
    with st.expander(f"长期标记（当前 {cur_lv} 级）"):
        cols=st.columns(4)
        for lv,col in zip([0,1,2,3],cols):
            bt="primary" if lv==cur_lv else "secondary"
            if col.button(lv_names[lv],key=f"ll_{lv}",use_container_width=True,type=bt):
                st.session_state.store.update_long(item["word"],lv)
                st.toast(f"✅ 标记为 {lv} 级"); st.rerun()


# ═══════════════════════════════════════════════════
# 完成
# ═══════════════════════════════════════════════════
def screen_done():
    sess=st.session_state.session
    if not sess: st.session_state.phase="main"; st.rerun(); return
    s=sess.stats()
    st.balloons()
    st.success(f"🎉 练习完成！{s['total']} 个变形条目全部通过 ✓")
    c1,c2=st.columns(2)
    with c1:
        if _gist_enabled():
            if st.button("🐙 保存到 Gist",type="primary",use_container_width=True):
                do_gist_save()
    with c2:
        st.download_button("⬇ 下载词库",data=st.session_state.store.export_csv(),
            file_name="jp_words.csv",mime="text/csv",use_container_width=True)
    if st.button("🏠 返回主页",use_container_width=True):
        st.session_state.phase="main"; st.session_state.session=None; st.rerun()


# ═══════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════
{
    "main":       screen_main,
    "gen":        screen_gen,
    "session":    screen_session,
    "done":       screen_done,
    "similarity": screen_similarity_session,
    "sim_done":   screen_sim_done,
}.get(st.session_state.phase, screen_main)()
