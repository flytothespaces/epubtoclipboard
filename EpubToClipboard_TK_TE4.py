import os
import sys
import json
import zipfile
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ══════════════════════════════════════════════════════
# 🔴 최우선: EXE 환경 맞춤형 전역 경로 및 고정 DB 폴더 확정
# ══════════════════════════════════════════════════════
_IS_FROZEN  = getattr(sys, 'frozen', False)
_IS_ANDROID = 'ANDROID_ARGUMENT' in os.environ or os.path.exists("/storage/emulated/0")

if _IS_FROZEN:
    BASE_DIR = os.path.dirname(sys.executable)      # 💡 진짜 물리적인 EXE 폴더 위치 확보
elif _IS_ANDROID:
    BASE_DIR = "/storage/emulated/0/Documents"
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 🎯 EXE 현재 폴더 하위에 'epubtoclipb_db' 고정 주소를 대못으로 박아버립니다.
if _IS_ANDROID:
    DB_ROOT_DIR = "/storage/emulated/0/Documents/epubtoclipb_db"
else:
    DB_ROOT_DIR = os.path.join(BASE_DIR, "epubtoclipb_db")

if not _IS_ANDROID:
    os.chdir(BASE_DIR) # 작업 디렉토리 고정

print(f"[시작] BASE_DIR    = {BASE_DIR}")
print(f"[시작] DB_ROOT_DIR = {DB_ROOT_DIR}")

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None


class PureEpubParser:
    def __init__(self, epub_path):
        self.path = epub_path
        self.zip_file = zipfile.ZipFile(epub_path)
        self.opf_dir = ""
        self.spine_items = []
        self._parse_manifest()

    def _parse_manifest(self):
        container_xml = self.zip_file.read("META-INF/container.xml")
        root = ET.fromstring(container_xml)
        ns = {'ns': 'urn:oasis:names:tc:opendocument:xmlns:container'}
        opf_path = root.find('.//ns:rootfile', ns).attrib['full-path']

        if "/" in opf_path:
            self.opf_dir = opf_path.rsplit("/", 1)[0] + "/"
        else:
            self.opf_dir = ""

        opf_xml = self.zip_file.read(opf_path)
        opf_root = ET.fromstring(opf_xml)

        ns_match = re.match(r'\{.*}', opf_root.tag)
        ns_url = ns_match.group(0)[1:-1] if ns_match else "http://www.idpf.org/2007/opf"
        opf_ns = {'opf': ns_url}

        manifest = {}
        for item in opf_root.findall('.//opf:manifest/opf:item', opf_ns):
            item_id = item.attrib.get('id')
            href = item.attrib.get('href')
            manifest[item_id] = self.opf_dir + href

        for itemref in opf_root.findall('.//opf:spine/opf:itemref', opf_ns):
            idref = itemref.attrib.get('idref')
            if idref in manifest:
                full_href = manifest[idref]
                if full_href.endswith(('.html', '.xhtml', '.htm')):
                    self.spine_items.append(full_href)

    def get_chapters(self):
        chapters = []
        for index, href in enumerate(self.spine_items):
            try:
                html_data = self.zip_file.read(href).decode('utf-8', errors='ignore')
                soup = BeautifulSoup(html_data, "html.parser")

                title = ""
                for h in ['h1', 'h2', 'h3', 'h4']:
                    h_tag = soup.find(h)
                    if h_tag and h_tag.get_text().strip():
                        title = h_tag.get_text().strip()
                        break

                if not title:
                    title_tag = soup.find('title')
                    if title_tag and title_tag.get_text().strip():
                        title = title_tag.get_text().strip()

                if not title:
                    title = Path(href).stem
                    if any(x in title.lower() for x in ['item', 'chapter', 'section']):
                        title = f"본문 파트 {index + 1}"

                chapters.append({
                    "title": title,
                    "href": href
                })
            except Exception as e:
                print(f"파일 추출 실패 ({href}):", e)
        return chapters


class EpubViewerTkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EPUB Viewer")
        self.root.geometry("500x750")
        self.root.configure(bg="#f2f2f2")

        # 💡 [해결] GUI 위젯 변수 초기화 등록 (외부 정의 경고 방지)
        self.file_label = None
        self.info_label = None
        self.progress_label = None
        self.trans_btn = None
        self.listbox = None
        self.status_state_label = None
        self.status_title_label = None
        self.chapter_entry = None
        self.bundle_entry = None
        self.next_btn = None
        self.memo_copy_btn = None
        self.memo_btn = None

        # 상태 및 데이터 관리 변수
        self.translated_titles = {}
        self.is_translated = False
        self.chapters = []
        self.current_filename = ""
        self.current_index = -1
        self.epub_path = ""
        # 💡 저장된 메모 파일이 있으면 자동 로드
        self.memo_text = ""
        try:
            memo_path = self.get_memo_file_path()
            if os.path.exists(memo_path):
                with open(memo_path, "r", encoding="utf-8") as f:
                    self.memo_text = f.read()
        except Exception as e:
            print("PC 메모 로드 실패:", e)
        # self.progress_file = "progress.json"

        # 윈도우 종료 시스템 이벤트 가로채기 복원
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)
        # 키보드 Esc 누를 때 종료 안내 팝업 바인딩
        self.root.bind("<Escape>", lambda event: self.on_window_close())

        self.setup_ui()

    def setup_ui(self):
        # 스타일 설정
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', font=('Noto Sans', 10), background='#595959', foreground='white')
        style.configure('Action.TButton', font=('Noto Sans', 12, 'bold'), background='#484848', foreground='white')

        # --- 상단 프레임 영역 ---
        top_frame = tk.Frame(self.root, bg="#f2f2f2", padx=10, pady=5)
        top_frame.pack(side=tk.TOP, fill=tk.X)

        # 1행: 파일 선택
        file_row = tk.Frame(top_frame, bg="#f2f2f2")
        file_row.pack(fill=tk.X, pady=2)
        self.file_label = tk.Label(file_row, text="EPUB 파일을 선택하세요", bg="#f2f2f2", fg="#262626", anchor="w")
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        file_btn = ttk.Button(file_row, text="파일 선택", command=self.open_epub)
        file_btn.pack(side=tk.RIGHT)

        # 2행: 회차 수 표시
        info_row = tk.Frame(top_frame, bg="#f2f2f2")
        info_row.pack(fill=tk.X, pady=2)
        self.info_label = tk.Label(info_row, text="회차 수: 0", bg="#f2f2f2", fg="#262626", anchor="w")
        self.info_label.pack(side=tk.LEFT)

        # 3행: 진행도 및 목차 번역
        progress_row = tk.Frame(top_frame, bg="#f2f2f2")
        progress_row.pack(fill=tk.X, pady=2)
        self.progress_label = tk.Label(progress_row, text="진행도: 없음", bg="#f2f2f2", fg="#262626", anchor="w")
        self.progress_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.trans_btn = ttk.Button(progress_row, text="목차 번역", command=self.confirm_and_translate)
        self.trans_btn.pack(side=tk.RIGHT)

        # --- 중단 프레임 영역 (리스트 박스 영역) ---
        middle_frame = tk.Frame(self.root, bg="#f2f2f2", padx=10, pady=5)
        middle_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(middle_frame, width=15)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Listbox 객체 바인딩
        self.listbox = tk.Listbox(
            middle_frame,
            font=('Noto Sans', 11),
            selectbackground="#b3c6ff",
            selectforeground="black",
            yscrollcommand=scrollbar.set,
            activestyle="none",
            bg="white"
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)

        # 아이템 더블클릭 또는 선택 시 변경 이벤트 연동
        self.listbox.bind('<<ListboxSelect>>', self.on_listbox_select)

        # --- 하단 프레임 영역 ---
        bottom_frame = tk.Frame(self.root, bg="#f2f2f2", padx=10, pady=5)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # 상단 라벨: 현재 상태 및 회차 번호
        self.status_state_label = tk.Label(
            bottom_frame,
            text="선택된 회차 없음",
            font=('Noto Sans', 11, 'bold'),
            bg="#f2f2f2",
            fg="#1a1a1a",
            anchor="center"
        )
        self.status_state_label.pack(fill=tk.X, pady=(2, 0))

        # 하단 라벨: 실제 소설 제목
        self.status_title_label = tk.Label(
            bottom_frame,
            text="",
            font=('Noto Sans', 9),
            bg="#f2f2f2",
            fg="#595959",
            anchor="center",
            justify="center",
            wraplength=460
        )
        self.status_title_label.pack(fill=tk.X, pady=(0, 5))

        # 2행: 회차 입력 제어행
        control_row = tk.Frame(bottom_frame, bg="#f2f2f2")
        control_row.pack(fill=tk.X, pady=4)

        self.chapter_entry = tk.Entry(control_row, width=8, font=('Noto Sans', 11), justify="center")
        self.chapter_entry.pack(side=tk.LEFT, padx=(0, 5))

        copy_btn = ttk.Button(control_row, text="현재 회차 복사", command=self.copy_selected_chapter)
        copy_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        prev_btn = ttk.Button(control_row, text="이전 회차 복사", command=self.copy_prev)
        prev_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # 3행: 회차 묶음 라인
        bundle_row = tk.Frame(bottom_frame, bg="#f2f2f2")
        bundle_row.pack(fill=tk.X, pady=4)
        bundle_label = tk.Label(bundle_row, text="회차 묶음:", font=('Noto Sans', 10), bg="#f2f2f2", fg="#262626")
        bundle_label.pack(side=tk.LEFT)
        self.bundle_entry = tk.Entry(bundle_row, width=6, font=('Noto Sans', 10), justify="center")
        self.bundle_entry.insert(0, "1")
        self.bundle_entry.pack(side=tk.LEFT, padx=5)

        # 메모
        self.memo_btn = ttk.Button(bundle_row, text="메모", command=self.open_memo_popup, width=8)
        self.memo_btn.pack(side="left", padx=5)

        self.memo_copy_btn = ttk.Button(bundle_row, text="메모 복사", command=self.copy_memo_to_clipboard, width=12)
        self.memo_copy_btn.pack(side="left", padx=5)

        # 4행: 대형 다음 회차 복사 버튼 (하단 철벽 안전 공간 확보)
        next_row = tk.Frame(bottom_frame, bg="#f2f2f2")
        next_row.pack(fill=tk.X, pady=(8, 0))

        style.configure('MegaAction.TButton', font=('Noto Sans', 14, 'bold'), background='#333333', foreground='white')

        self.next_btn = ttk.Button(
            next_row,
            text="다음 회차 복사",
            style='MegaAction.TButton',
            command=self.copy_next
        )
        self.next_btn.pack(fill=tk.X, ipady=15, pady=(0, 35))

    def open_memo_popup(self):
        # 1. 고해상도 대응
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass

        # 2. Toplevel 팝업 창 생성
        memo_win = tk.Toplevel(self.root)
        memo_win.title("메모장")

        # 💡 [수정] 외부 폰트 주입 로직 제거 및 안드로이드 시스템 기본 폰트 매핑
        is_android = 'ANDROID_ARGUMENT' in os.environ or os.path.exists("/storage/emulated/0")

        if is_android:
            # 안드로이드 환경에서는 시스템 기본 폰트("")를 사용하여 용량 최적화 및 가독성 확보
            memo_font_family = ""
        else:
            # 윈도우 PC 환경에서는 기존처럼 맑은 고딕 유지
            memo_font_family = "맑은 고딕"

        # 3. 화면 크기 계산 (가로 90%, 세로 90% 상단 정렬)
        screen_width = memo_win.winfo_screenwidth()
        screen_height = memo_win.winfo_screenheight()
        popup_width = int(screen_width * 0.9)
        popup_height = int(screen_height * 0.9)
        memo_win.geometry(f"{popup_width}x{popup_height}+{int((screen_width - popup_width) / 2)}+30")

        # 4. 프레임 배치
        toolbar = ttk.Frame(memo_win, padding=5)
        toolbar.pack(fill="x", side="top")
        for i in range(4): toolbar.grid_columnconfigure(i, weight=1)

        bottom_frame = ttk.Frame(memo_win, padding=5)
        bottom_frame.pack(fill="x", side="bottom")

        text_frame = ttk.Frame(memo_win)
        text_frame.pack(expand=True, fill="both", padx=10, pady=2)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        # 💡 [적용] 결정된 플랫폼별 폰트 패밀리 주입
        text_widget = tk.Text(text_frame, wrap="word", font=(memo_font_family, 12),
                              undo=True, yscrollcommand=scrollbar.set)
        text_widget.insert("1.0", self.memo_text)
        text_widget.pack(expand=True, fill="both", side="left")
        scrollbar.config(command=text_widget.yview)

        # 5. 버튼 기능 정의
        def select_all():
            text_widget.tag_add("sel", "1.0", "end-1c")
            text_widget.focus_set()

        def copy_text():
            try:
                selected = text_widget.get("sel.first", "sel.last")
                memo_win.clipboard_clear()
                memo_win.clipboard_append(selected)
            except tk.TclError:
                pass

        def cut_text():
            try:
                copy_text();
                text_widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass

        def paste_text():
            try:
                clipboard = memo_win.clipboard_get()
                try:
                    text_widget.delete("sel.first", "sel.last")
                except tk.TclError:
                    pass
                text_widget.insert("insert", clipboard)
            except tk.TclError:
                pass

        # 버튼 생성
        ttk.Button(toolbar, text="전체", command=select_all).grid(row=0, column=0, sticky="ew", padx=3)
        ttk.Button(toolbar, text="자르기", command=cut_text).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(toolbar, text="복사", command=copy_text).grid(row=0, column=2, sticky="ew", padx=3)
        ttk.Button(toolbar, text="붙이기", command=paste_text).grid(row=0, column=3, sticky="ew", padx=3)

        # 6. 안드로이드 키보드 충돌 최소화 바인딩 유지
        if is_android:
            def on_key_release(event):
                pass

            text_widget.bind("<KeyRelease>", on_key_release)

        # 7. 단축키 바인딩
        text_widget.bind("<Control-Key-a>", lambda e: [select_all(), "break"][1])
        text_widget.bind("<Control-Key-A>", lambda e: [select_all(), "break"][1])
        text_widget.bind("<Control-Key-c>", lambda e: [copy_text(), "break"][1])
        text_widget.bind("<Control-Key-v>", lambda e: [paste_text(), "break"][1])
        text_widget.bind("<Control-Key-x>", lambda e: [cut_text(), "break"][1])

        # 8. 저장 및 닫기
        def save_and_close():
            self.memo_text = text_widget.get("1.0", "end-1c")
            try:
                with open(self.get_memo_file_path(), "w", encoding="utf-8") as f:
                    f.write(self.memo_text)
            except Exception as e:
                print("메모 자동 저장 실패:", e)
            memo_win.destroy()

        save_btn = ttk.Button(bottom_frame, text="저장 후 닫기", command=save_and_close)
        save_btn.pack(pady=5)
        memo_win.protocol("WM_DELETE_WINDOW", save_and_close)
        text_widget.focus_set()

    def copy_memo_to_clipboard(self):
        if self.memo_text.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(self.memo_text)

            # 💡 [변경] 팝업 알림창 대신 상태 표시줄 라벨에 텍스트를 띄웁니다.
            # (유저님의 상태 표시 라벨 변수명이 다르면 self.status_label 부분을 수정해 주세요!)
            if hasattr(self, 'status_title_label'):
                self.status_title_label.config(text="상태: 메모장 전체 내용 복사 완료!")
            elif hasattr(self, 'status_title_label'):
                self.status_title_label.config(text="상태: 메모장 전체 내용 복사 완료!")
        else:
            if hasattr(self, 'status_title_label'):
                self.status_title_label.config(text="상태: 메모장이 비어 있습니다.")

    def on_window_close(self):
        # Tkinter 표준 대화상자를 사용해 철벽 종료 방어 구현
        if messagebox.askyesno("종료 확인", "프로그램을 종료하시겠습니까?\n종료 시 현재 진행도가 자동 저장됩니다."):
            try:
                if self.current_filename and self.current_index != -1:
                    self.save_progress()
            except Exception as e:
                print("종료 전 자동 저장 실패:", e)
            self.root.destroy()

    def _get_db_dir(self):
        path = DB_ROOT_DIR
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except Exception as e:
            print(f"[경로 생성 실패] {path} : {e}")
            return None

    def open_epub(self):
        # 💡 안드로이드(Pydroid3) 외부 저장소 표준 최상단 경로 설정
        android_shared_storage = "/storage/emulated/0"

        # 만약 해당 경로가 존재하면(안드로이드 환경이면) 거기를 시작점으로 사용, 아니면 PC 사용자 홈폴더 사용
        if os.path.exists(android_shared_storage):
            init_path = android_shared_storage
            print(f"[안드로이드 탐색기 구동] 시작 경로: {init_path}")
        else:
            init_path = os.path.expanduser("~")
            print(f"[PC 탐색기 구동] 시작 경로: {init_path}")

        try:
            path = filedialog.askopenfilename(
                initialdir=init_path,
                filetypes=[("EPUB Files", "*.epub")]
            )
            if path:
                self.load_epub(path)
        except Exception as e:
            print("파일 탐색기 구동 실패:", e)

    def load_epub(self, path):
        self.translated_titles = {}
        self.is_translated = False
        self.trans_btn.config(text="목차 번역")

        self.epub_path = path
        self.current_filename = Path(path).name
        self.file_label.config(text=self.current_filename)

        # 고속화 단계: 로컬 캐시 조회
        cached_toc = self.load_epubtoclipb_db()

        if cached_toc:
            print("🎉 [초고속 로딩] 로컬 JSON에서 원문 구조 및 번역 목차를 즉시 복원합니다.")
            self.chapters = cached_toc["chapters"]

            raw_trans = cached_toc.get("translated_titles", {})
            self.translated_titles = {int(k): v for k, v in raw_trans.items()}

            count = len(self.chapters)
            self.info_label.config(text=f"회차 수: {count}")

            if self.translated_titles:
                self.refresh_listbox(self.translated_titles)
                self.trans_btn.config(text="원문 목차")
                self.is_translated = True
            else:
                self.refresh_listbox({i: ch['title'] for i, ch in enumerate(self.chapters)})

            progress = self.load_progress()
            last = progress.get(self.current_filename, 1)
            if count > 0:
                self.select_list_item(max(0, min(last - 1, count - 1)))
                # 🎯 여기에 명시적으로 라벨 업데이트 코드를 추가합니다.
                self.progress_label.config(text=f"진행도: {last}/{count}")
            return

        print("🐢 [최초 로딩] 캐시가 없어 전체 목차 필터링을 진행합니다.")
        parser = PureEpubParser(path)
        raw_chapters = parser.get_chapters()
        self.chapters = []

        for item in raw_chapters:
            title = item.get('title', '').strip()
            if any(kw in title.lower() for kw in ['cover', '표지', 'title', '제목', '안내']):
                print(f"무효 회차 스킵 처리: {title}")
                continue
            self.chapters.append(item)

        self.refresh_listbox({i: ch['title'] for i, ch in enumerate(self.chapters)})
        count = len(self.chapters)
        self.info_label.config(text=f"회차 수: {count}")

        self.save_epubtoclipb_db()

        progress = self.load_progress()
        last = progress.get(self.current_filename, 1)
        if count > 0:
            self.select_list_item(max(0, min(last - 1, count - 1)))
            self.progress_label.config(text=f"진행도: {last}/{count}")

    def refresh_listbox(self, title_map):
        self.listbox.delete(0, tk.END)
        for i in range(len(self.chapters)):
            item_text = f" {i + 1}. {title_map.get(i, self.chapters[i]['title'])}"
            self.listbox.insert(tk.END, item_text)

            # 홀수/짝수 라인 색상 번갈아 매칭하여 가독성 가공(줄무늬 디자인 대체)
            if i % 2 == 0:
                self.listbox.itemconfig(i, bg="white")
            else:
                self.listbox.itemconfig(i, bg="#ecf2f9")

    def on_listbox_select(self, event):
        selection = self.listbox.curselection()
        if selection:
            self.on_select_item(selection[0])

    def on_select_item(self, index):
        self.current_index = index
        if self.is_translated and index in self.translated_titles:
            display_title = self.translated_titles[index]
        else:
            display_title = self.chapters[index]['title']

        display_num = index + 1

        # 💡 나누어 놓은 라벨에 각각 텍스트 주입
        self.status_state_label.config(text=f"선택된 회차: [{display_num}]")
        self.status_title_label.config(text=display_title)

        self.chapter_entry.delete(0, tk.END)
        self.chapter_entry.insert(0, str(display_num))

    def select_list_item(self, index):
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.listbox.see(index)  # 스크롤 포커스 이동 조치
        self.on_select_item(index)

    def confirm_and_translate(self):
        # 1. 만약 목록에 데이터가 아예 없다면 작동 안 함
        if not self.chapters:
            return

        # 2. [현재 번역 목록을 보고 있는 상태] -> 원문 목차로 전환
        if self.is_translated:
            # 💡 기존의 리스트박스 초기화(원문 복원) 로직 반영
            self.refresh_listbox({i: ch['title'] for i, ch in enumerate(self.chapters)})
            self.is_translated = False  # 리스트박스 상태를 원문 상태로 변경
            self.trans_btn.config(text="번역 목차")  # 버튼은 다시 번역본으로 갈 수 있게 토글

            # 리스트박스 위치 복원
            if self.current_index != -1:
                self.select_list_item(self.current_index)
            return

        # 3. [현재 원문 목차를 보고 있는 상태] -> 번역 목차로 전환 시도
        # 이미 이전에 번역해 둔 데이터(캐시 등)가 내부에 존재하는 경우 (구글 API 호출 안 함)
        if self.translated_titles:
            self.refresh_listbox(self.translated_titles)
            self.is_translated = True  # 리스트박스 상태를 번역 상태로 변경
            self.trans_btn.config(text="원문 목차")  # 버튼은 다시 원문으로 갈 수 있게 토글

            if self.current_index != -1:
                self.select_list_item(self.current_index)
            return

        # 4. [완전 최초 로딩 상태] 내부에 번역 데이터가 아예 없을 때만 팝업창을 띄우고 구글 API 번역 실행
        total_count = len(self.chapters)

        # 💡 [복원] Tkinter 표준 메시지 박스로 안내 후 유저가 '예(Yes)'를 눌렀을 때만 번역 시작
        if messagebox.askyesno(
                "목차 번역 안내",
                f"현재 문서의 목차는 총 {total_count}개입니다.\n\n50화 단위로 제목을 번역합니다.\n\n인터넷 연결로 작업을 시작할까요?"
        ):
            self.translate_chapter_list()

    def translate_chapter_list(self):
        if self.translated_titles and self.is_translated:
            self.refresh_listbox(self.translated_titles)
            self.trans_btn.config(text="원문 보기")
            return

        self.trans_btn.config(text="번역 중...", state=tk.DISABLED)
        self.root.update()  # UI 강제 동기화 새로고침

        translator = GoogleTranslator(source='auto', target='ko') if GoogleTranslator else None
        translation_targets = []
        for i, ch in enumerate(self.chapters):
            original_title = ch['title']
            if original_title and not original_title.isdigit() and not any(ord('가') <= ord(char) <= ord('힣') for char in original_title):
                translation_targets.append(f"{i}_###_{original_title}")

        translated_map = {i: ch['title'] for i, ch in enumerate(self.chapters)}
        chunk_size = 50

        if translation_targets and translator:
            for chunk_idx in range(0, len(translation_targets), chunk_size):
                chunk = translation_targets[chunk_idx:chunk_idx + chunk_size]
                try:
                    combined_text = "\n".join(chunk)
                    translated_combined = translator.translate(combined_text)
                    translated_lines = translated_combined.split("\n")

                    for line in translated_lines:
                        if "_###_" in line:
                            try:
                                parts = line.split("_###_", 1)
                                idx = int(parts[0].strip())
                                val = parts[1].strip()
                                translated_map[idx] = val
                            except:
                                pass
                except Exception as e:
                    print("번역 청크 처리 실패:", e)

        self.translated_titles = translated_map
        self.save_epubtoclipb_db()

        self.refresh_listbox(self.translated_titles)
        self.trans_btn.config(text="원문 목차", state=tk.NORMAL)
        self.is_translated = True

    def load_progress(self):
        target_path = self.get_progress_file_path()
        if not os.path.exists(target_path):
            return {}
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    def save_progress(self):
        if not self.current_filename:
            return
        target_path = self.get_progress_file_path()
        progress = self.load_progress()
        progress[self.current_filename] = self.current_index + 1
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("진행도 저장 실패:", e)

    def get_bundle_size(self):
        try:
            val = int(self.bundle_entry.get())
            return max(1, val)
        except:
            return 1

    def get_chapter_text(self, index):
        # 💡 [수정] index를 int()로 강제 형변환하여 리스트 인덱스 접근 경고를 해결합니다.
        target_idx = int(index)
        target_href = self.chapters[target_idx]["href"]

        with zipfile.ZipFile(self.epub_path) as z:
            html = z.read(target_href).decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text("\n")  # type: ignore

    def copy_to_clipboard(self, text):
        # 외부 helper 의존을 제거하고 Tkinter 내장 클립보드 활용으로 획기적 속도 상승
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
        except Exception as e:
            print("Tkinter 클립보드 복사 실패, 우회 시도:", e)

    def copy_selected_chapter(self):
        bundle_size = self.get_bundle_size()

        try:
            if self.chapter_entry.get():
                self.current_index = int(self.chapter_entry.get()) - 1
        except:
            pass

        if self.current_index < 0 or self.current_index >= len(self.chapters):
            return

        end_idx = min(self.current_index + bundle_size, len(self.chapters))
        text_to_copy = ""
        for i in range(self.current_index, end_idx):
            text_to_copy += self.get_chapter_text(i) + "\n\n"

        self.copy_to_clipboard(text_to_copy)

        self.save_progress()
        self.progress_label.config(text=f"진행도: {self.current_index + 1}/{len(self.chapters)}")

        display_num = self.current_index + 1
        # self.current_title.config(text=f"복사 완료: [{display_num}] {self.chapters[self.current_index]['title']} 외 {end_idx - self.current_index - 1}건")
        self.status_state_label.config(text=f"📋 복사 완료: [{display_num}]")
        summary_title = f"{self.chapters[self.current_index]['title']}\n(외 {end_idx - self.current_index - 1}건 포함)" if (end_idx - self.current_index - 1) > 0 else self.chapters[self.current_index][
            'title']
        self.status_title_label.config(text=summary_title)

        self.select_list_item(self.current_index)

    def copy_prev(self):
        bundle_size = self.get_bundle_size()
        self.current_index = max(0, self.current_index - bundle_size)
        self._update_list_and_copy()

    def copy_next(self):
        bundle_size = self.get_bundle_size()
        self.current_index = min(self.current_index + bundle_size, len(self.chapters) - 1)
        self._update_list_and_copy()

    def _update_list_and_copy(self):
        self.select_list_item(self.current_index)
        self.copy_selected_chapter()

    def save_epubtoclipb_db(self):
        cache_path = self.get_epubtoclipb_db_path()
        if not cache_path or not self.chapters:
            return
        try:
            cache_data = {
                "chapters": self.chapters,
                "translated_titles": {str(k): v for k, v in self.translated_titles.items()}
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print(f"[캐시 저장] 통합 목차 파일 저장 완료: {cache_path}")
        except Exception as e:
            print(f"[캐시 오류] 목차 파일 저장 실패: {e}")

    def load_epubtoclipb_db(self):
        cache_path = self.get_epubtoclipb_db_path()
        if not cache_path or not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            if "chapters" not in cache_data:
                return None

            return cache_data
        except Exception as e:
            print(f"[캐시 오류] 목차 로드 중 실패: {e}")
            return None

    def get_epubtoclipb_db_path(self):
        if not self.current_filename:
            return None
        cache_dir = self._get_db_dir()
        if not cache_dir:
            return None
        base_name = os.path.splitext(self.current_filename)[0]
        return os.path.join(cache_dir, f"{base_name}_toc.json")

    def get_progress_file_path(self):
        cache_dir = self._get_db_dir()
        if not cache_dir:
            return "progress.json"  # 최악의 우회책
        return os.path.join(cache_dir, "progress.json")

    def get_memo_file_path(self):
        cache_dir = self._get_db_dir()
        if not cache_dir:
            return "memo.txt"  # 최악의 우회책
        return os.path.join(cache_dir, "memo.txt")

if __name__ == "__main__":
    root = tk.Tk()
    app = EpubViewerTkApp(root)
    root.mainloop()