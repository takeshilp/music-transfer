import os, sys, threading, traceback
from math import ceil

from PySide6.QtCore import QStandardPaths, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget, QComboBox)

from . import __version__, theme, update
from .common import CONFIG_PATH, LIKED, AppError, Cancelled, load_config, save_config
from .spotify import CLIENT_ID, REDIRECT_URI, SpotifyService
from .matching import strip_tags
from .transfer import build_jobs, copy_jobs, export_csv, match_jobs, track_key, write_jobs
from .yandex import TOKEN_URL, YandexService


class Worker(QThread):
    """Runs fn(progress) off the UI thread; progress(text, done, total), the result and errors come back as signals.

    progress raises Cancelled once the stop event is set; a cancelled run ends with done(None)."""
    progress = Signal(str, int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, stop=None):
        super().__init__()  # no parent: the window keeps the only reference
        self.fn, self.stop = fn, stop

    def _step(self, text, done, total):
        if self.stop and self.stop.is_set():
            raise Cancelled()
        self.progress.emit(text, done, total)

    def run(self):
        try:
            self.done.emit(self.fn(self._step))
        except Cancelled:
            self.done.emit(None)
        except AppError as e:
            self.failed.emit(str(e))
        except Exception as e:  # a bug, not a user error: keep the app alive and say what broke
            traceback.print_exc()  # stderr only (no-op in a windowed build); no locals, so no tokens
            self.failed.emit(f"Непредвиденная ошибка: {type(e).__name__}: {e}")


def _fill(combo, services):
    """Replace the items with these accounts (shown by label), keeping the current pick when it is still there."""
    cur = combo.currentData()
    combo.clear()
    for s in services:
        combo.addItem(s.label, s)
    combo.setCurrentIndex(next((i for i, s in enumerate(services) if s is cur), 0))


def _fmt(t):
    return f"{', '.join(t.artists)} — {t.title}"


def _line(t):
    m, s = divmod(t.duration_ms // 1000, 60)
    return " · ".join(x for x in (_fmt(t), t.album, f"{m}:{s:02d}") if x)


def _card(title, content):
    """A rounded titled panel (QFrame#card in the theme) around a layout."""
    card, head = QFrame(), QLabel(title)
    card.setObjectName("card")
    head.setObjectName("title")
    v = QVBoxLayout(card)
    v.setContentsMargins(16, 12, 16, 16)
    v.addWidget(head)
    v.addLayout(content)
    return card


def _restyle(w, prop, value):
    """Set a dynamic property the stylesheet selects on, and make Qt re-read the stylesheet for it."""
    w.setProperty(prop, value)
    w.style().unpolish(w)
    w.style().polish(w)


SP_WAIT = "Войдите в Spotify в открывшемся окне браузера. Ждём ответа до 3 минут…"
PER_NAME = "Название плейлиста из лайков (необязательно)"  # per-playlist mode: the liked tracks' playlist
MERGED_NAME = "Название нового плейлиста"
FOLLOW_HEAD = "Подписки на чужие плейлисты"
PICK, SEARCH, SKIP = 1, 2, 3  # PickDialog results; PICK is QDialog's Accepted, 0 (Rejected) is «Отмена»
CREATE_APP_URL = "https://developer.spotify.com/dashboard/create"
DASHBOARD_URL = "https://developer.spotify.com/dashboard"
APP_FORM = (("App name", "Music Transfer"),  # the Dashboard form's fields; app names may not contain "Spotify"
            ("App description", "Copies my playlists between Spotify and Yandex Music"),
            ("Redirect URIs", REDIRECT_URI))


def _hint(text):
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    label.setOpenExternalLinks(True)
    return label


class SpotifyGuide(QDialog):
    """How to get a client ID: the Dashboard form's values with copy buttons. Non-modal and on top, so it stays
    beside the browser; the main window fills the ID in by itself once it is copied (MainWindow._clipboard_changed)."""

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Client ID для Spotify")
        self.setMinimumWidth(700)  # no resize(): show() then fits the height to the wrapped text
        self.open_btn = QPushButton("Открыть страницу создания приложения")
        self.open_btn.setProperty("accent", True)
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(CREATE_APP_URL)))
        form = QGridLayout()
        for row, (name, value) in enumerate(APP_FORM):
            field, copy = QLineEdit(value), QPushButton("Копировать")
            field.setReadOnly(True)
            field.setCursorPosition(0)  # show the start of a long value
            copy.setMinimumWidth(copy.fontMetrics().horizontalAdvance("Скопировано") + 48)  # room for the swap
            copy.clicked.connect(lambda _=False, v=value, b=copy: self._copy(v, b))
            form.addWidget(QLabel(name), row, 0)
            form.addWidget(field, row, 1)
            form.addWidget(copy, row, 2)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)
        v.addWidget(_hint(f'1. Откройте <a href="{CREATE_APP_URL}">developer.spotify.com</a> и войдите в Spotify, '
                          "если попросит."))
        v.addWidget(self.open_btn)
        v.addWidget(_hint("2. Заполните форму: «Копировать» здесь, Ctrl+V на сайте."))
        v.addLayout(form)
        v.addWidget(_hint("3. Под Redirect URIs нажмите «Add», отметьте «Web API» и согласие с правилами, затем «Save»."))
        v.addWidget(_hint("4. На странице приложения скопируйте Client ID — программа подставит его сама."))
        v.addWidget(_hint("Друзей добавьте там же: Settings → User Management, имя и email их Spotify, до 5 человек."))

    def _copy(self, value, btn):
        QApplication.clipboard().setText(value)
        btn.setText("Скопировано")
        QTimer.singleShot(1500, lambda: btn.setText("Копировать"))


class SecondAccountGuide(QDialog):
    """Before a second Spotify account can log in, the app owner lists it in User Management (Dev Mode lets only
    listed users in, 403 otherwise); the client ID is the same, so nothing else is needed."""

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Второй аккаунт Spotify")
        self.setMinimumWidth(600)  # no resize(): show() then fits the height to the wrapped text
        self.open_btn = QPushButton("Открыть Spotify Dashboard")
        self.open_btn.setProperty("accent", True)
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DASHBOARD_URL)))
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)
        v.addWidget(_hint(f'1. Откройте <a href="{DASHBOARD_URL}">developer.spotify.com/dashboard</a> под аккаунтом, '
                          "который создавал приложение, и выберите это приложение."))
        v.addWidget(self.open_btn)
        v.addWidget(_hint("2. Вкладка User Management: впишите имя и email второго аккаунта Spotify и нажмите "
                          "«Add user». Без этого Spotify не пустит его в программу (ошибка 403)."))
        v.addWidget(_hint("3. Здесь нажмите «Войти» в строке «Spotify (второй)». На странице Spotify нажмите "
                          "«Не вы?» и войдите во второй аккаунт."))  # nbsp: keep «Не вы?» on one line


class PickDialog(QDialog):
    """Manual match for one source track: the target's search results, unavailable ones listed but not choosable.
    Closes with PICK, SKIP or SEARCH (artist/title edited); the search itself runs in the window's worker."""

    def __init__(self, parent, src, artist, title, found):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # each «Искать» makes a new dialog; hidden ones hold ~1 MB each
        self.setWindowTitle("Выбор трека")
        self.setMinimumWidth(640)
        head = QLabel(f"Исходный трек: {_line(src)}")
        head.setTextFormat(Qt.TextFormat.PlainText)  # titles come from public catalogs: no rich text or links
        head.setWordWrap(True)
        self.artist, self.title, self.list = QLineEdit(artist), QLineEdit(title), QListWidget(self)  # parented first: the theme's item padding applies to rows added later
        self.artist.setPlaceholderText("Исполнитель")
        self.title.setPlaceholderText("Название")
        self.search_btn, self.pick_btn = QPushButton("Искать"), QPushButton("Выбрать")
        self.skip_btn, cancel = QPushButton("Не переносить"), QPushButton("Отмена")
        self.search_btn.setDefault(True)  # Enter in a field searches
        self.pick_btn.setProperty("accent", True)
        self.skip_btn.setToolTip("Трек не попадёт в новый плейлист и останется в списке ненайденных")
        for t in found:
            item = QListWidgetItem(_line(t) if t.available else f"{_line(t)} · недоступен")
            item.setData(Qt.ItemDataRole.UserRole, t)
            if not t.available:
                item.setFlags(Qt.ItemFlag.NoItemFlags)  # cannot be added to a playlist
            self.list.addItem(item)
        self.list.setCurrentRow(next((r for r, t in enumerate(found) if t.available), -1))  # «Выбрать» works at once
        self.list.itemActivated.connect(self._choose)  # double click and Enter (Enter would otherwise press «Искать»)
        self.search_btn.clicked.connect(lambda: self.done(SEARCH))
        self.pick_btn.clicked.connect(self._choose)
        self.skip_btn.clicked.connect(lambda: self.done(SKIP))
        cancel.clicked.connect(self.reject)
        query = QHBoxLayout()
        query.addWidget(self.artist, 1)
        query.addWidget(self.title, 2)
        query.addWidget(self.search_btn)
        buttons = QHBoxLayout()
        buttons.addWidget(self.skip_btn)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.pick_btn)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)
        v.addWidget(head)
        v.addLayout(query)
        v.addWidget(self.list)
        if not found:
            v.addWidget(_hint("Ничего не найдено. Измените исполнителя или название и нажмите «Искать»."))
        v.addLayout(buttons)

    def picked(self):
        """The chosen track, or None (nothing chosen, or unavailable: setCurrentRow still reaches a disabled item)."""
        item = self.list.currentItem()
        t = item.data(Qt.ItemDataRole.UserRole) if item else None
        return t if t and t.available else None

    def _choose(self, *_):
        if self.picked():
            self.done(PICK)


class MainWindow(QMainWindow):
    code_ready = Signal(str, str)  # Yandex device code and page, emitted from the worker thread

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Music Transfer {__version__} — Spotify ↔ Яндекс Музыка")
        self.resize(1100, 750)
        try:
            cid = str(load_config().get("spotify_client_id") or "").strip()
            self.spotify, sp_error = (SpotifyService(cid) if cid else None), ""
        except AppError as e:
            self.spotify, sp_error = None, f"{e} ({CONFIG_PATH})<br>"
        # slot 2: a second account of the same service, for moving from an old account to a new one
        self.spotify2 = SpotifyService(cid, 2) if self.spotify else None
        self.yandex, self.yandex2 = YandexService(), YandexService(2)
        self.services = [s for s in (self.spotify, self.spotify2, self.yandex, self.yandex2) if s is not None]
        self.worker = self.jobs = self.follows = self.pair = self.loaded = self.on_done = self.stop = None
        self.guide = self.guide2 = self.picker = None
        self.rows = []  # match-table row -> (job, index into job.results), for _pick
        self.playlists, self.own, self.opened, self.followed_done = [], [], set(), False
        self.code_ready.connect(self._show_code)
        QApplication.clipboard().dataChanged.connect(self._clipboard_changed)
        self._build(sp_error)
        self._refresh()
        self._run("Восстановление входа…", self._restore_all)

    def _build(self, sp_error):
        g = QGridLayout()
        self.sp_status, self.sp_id, self.sp_btn = QLabel(), QLineEdit(), QPushButton()
        self.sp_id.setPlaceholderText("Client ID приложения Spotify")
        self.sp_btn.clicked.connect(self._spotify_click)
        self.sp_hint = QLabel(f'{sp_error}Нужен Client ID вашего приложения Spotify — <a href="#guide">как его получить '
                              "за 2 минуты</a>. Скопированный ID появится в поле сам и сохранится после входа.")
        self.sp_hint.linkActivated.connect(self._show_guide)
        self.ya_status, self.token, self.ya_btn = QLabel(), QLineEdit(), QPushButton()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("Токен или вся ссылка из адресной строки")
        self.ya_btn.clicked.connect(self._yandex_click)
        self.alt = alt = QLabel('<a href="#">Другой способ: вставить токен</a>')
        alt.linkActivated.connect(self._toggle_token)
        self.ya_hint = QLabel(f'Откройте <a href="{TOKEN_URL}">страницу входа Яндекса</a>, войдите и разрешите доступ. '
                              "В адресной строке появится ссылка с access_token=… — сразу скопируйте её целиком, "
                              "вставьте в поле и нажмите «Войти».")
        for hint in (self.sp_hint, self.ya_hint):
            hint.setObjectName("hint")
            hint.setWordWrap(True)
        self.ya_hint.setOpenExternalLinks(True)  # sp_hint's link opens the guide instead
        self.token.setVisible(False)
        self.ya_hint.setVisible(False)
        # second accounts: hidden until «+ второй аккаунт», for moving one person's library to a new account
        self.sp2_status, self.sp2_btn, self.ya2_status, self.ya2_btn = QLabel(), QPushButton(), QLabel(), QPushButton()
        self.sp2_btn.clicked.connect(lambda: self._second_click(self.spotify2))
        self.ya2_btn.clicked.connect(lambda: self._second_click(self.yandex2))
        self.sp_more = QLabel('<a href="sp">+ второй аккаунт Spotify</a>')
        self.ya_more = QLabel('<a href="ya">+ второй аккаунт Яндекса</a>')
        for more in (self.sp_more, self.ya_more):
            more.linkActivated.connect(self._open_second)
        self.sp2_help = QLabel('<a href="#">как подключить второй аккаунт Spotify</a>')
        self.sp2_help.linkActivated.connect(self._show_second_guide)
        self.sp2_row = (QLabel("Spotify (второй)"), self.sp2_status, self.sp2_btn)
        self.ya2_row = (QLabel("Яндекс Музыка (второй)"), self.ya2_status, self.ya2_btn)
        g.addWidget(QLabel("Spotify"), 0, 0)
        g.addWidget(self.sp_status, 0, 1)
        g.addWidget(self.sp_id, 0, 2)
        g.addWidget(self.sp_btn, 0, 3)
        g.addWidget(self.sp_hint, 1, 0, 1, 4)
        for c, w in zip((0, 1, 3), self.sp2_row):
            g.addWidget(w, 2, c)
        g.addWidget(self.sp2_help, 2, 2)
        g.addWidget(QLabel("Яндекс Музыка"), 3, 0)
        g.addWidget(self.ya_status, 3, 1)
        g.addWidget(self.token, 3, 2)
        g.addWidget(self.ya_btn, 3, 3)
        for c, w in zip((0, 1, 3), self.ya2_row):
            g.addWidget(w, 4, c)
        links = QHBoxLayout()
        for w in (alt, self.sp_more, self.ya_more):
            links.addWidget(w)
        links.addStretch()
        g.addLayout(links, 5, 1, 1, 3)
        g.addWidget(self.ya_hint, 6, 0, 1, 4)
        g.setColumnStretch(2, 1)

        self.src, self.dst, self.reload = QComboBox(), QComboBox(), QPushButton("Обновить")
        for combo in (self.src, self.dst):
            theme.round_popup(combo)
        self.src.activated.connect(self._refresh)
        self.dst.activated.connect(self._refresh)
        self.reload.clicked.connect(self._load_playlists)
        pick = QGridLayout()  # one row each, full width: "Spotify · <nick>" is not cut
        pick.addWidget(QLabel("Откуда:"), 0, 0)
        pick.addWidget(self.src, 0, 1)
        pick.addWidget(self.reload, 0, 2)  # reloads the source's playlists
        pick.addWidget(QLabel("Куда:"), 1, 0)
        pick.addWidget(self.dst, 1, 1, 1, 2)
        pick.setColumnStretch(1, 1)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._invalidate)
        all_on, all_off = QPushButton("Выбрать все"), QPushButton("Снять все")
        all_on.clicked.connect(lambda: self._check_all(Qt.CheckState.Checked))
        all_off.clicked.connect(lambda: self._check_all(Qt.CheckState.Unchecked))
        checks = QHBoxLayout()
        checks.addWidget(all_on)
        checks.addWidget(all_off)
        mode = QGroupBox("Режим")
        m = QVBoxLayout(mode)
        self.per, self.merged, self.name = QRadioButton("По плейлистам"), QRadioButton("В один плейлист"), QLineEdit()
        self.per.setChecked(True)
        self.name.setPlaceholderText(PER_NAME)
        self.merged.toggled.connect(self._mode_changed)
        self.name.textChanged.connect(self._update_buttons)
        for w in (self.per, self.merged, self.name):
            m.addWidget(w)
        self.find_btn, self.go_btn = QPushButton("Найти треки"), QPushButton("Перенести")
        for b in (self.find_btn, self.go_btn):
            b.setProperty("accent", True)
        self.find_btn.clicked.connect(self._find)
        self.go_btn.clicked.connect(self._transfer)
        acts = QHBoxLayout()
        acts.addWidget(self.find_btn)
        acts.addWidget(self.go_btn)
        left = QVBoxLayout()
        left.addLayout(pick)
        left.addWidget(self.list)
        left.addLayout(checks)
        left.addWidget(mode)
        left.addLayout(acts)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.activated.connect(lambda i: self._pick(i.row()))  # double click or Enter
        self.csv_btn = QPushButton("Сохранить ненайденные в CSV")
        self.csv_btn.clicked.connect(self._save_csv)
        right = QVBoxLayout()
        right.addWidget(self.table)
        right.addWidget(self.csv_btn)

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(_card("Плейлисты", left), 1)
        body.addWidget(_card("Результат", right), 2)
        root = QVBoxLayout()
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)
        root.addWidget(_card("Аккаунты", g))
        root.addLayout(body)
        central = QWidget()
        central.setObjectName("backdrop")  # the theme paints the green glow on it
        central.setLayout(root)
        self.setCentralWidget(central)
        self.status, self.bar, self.cancel_btn = QLabel(), QProgressBar(), QPushButton("Отмена")
        self.status.setOpenExternalLinks(True)  # the Yandex code message links to its page
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.update_btn = QPushButton("Проверить обновление")
        self.update_btn.clicked.connect(self._check_update)
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.bar)
        self.statusBar().addPermanentWidget(self.cancel_btn)
        self.statusBar().addPermanentWidget(self.update_btn)

    # --- background work: functions passed to _run run in the worker thread and must never touch widgets ---

    def _cancel(self):
        self.stop.set()
        self.cancel_btn.setEnabled(False)  # the run stops at its next step; a playlist being written is finished first
        self.status.setText(self.stopping)

    def _run(self, text, fn, on_done=lambda _: None, stop=None, stopping="Отмена…"):
        """stop: a threading.Event the work checks; «Отмена» is shown only when it is given (logins, find, transfer).
        stopping: the status once «Отмена» is pressed. A cancelled run ends with on_done(None)."""
        if self.worker:
            self.worker.wait()  # the last thread may still be returning from run(); dropping it while running aborts the process
        self.on_done, self.worker, self.stop, self.stopping = on_done, (w := Worker(fn, stop)), stop, stopping
        for s in self.services:  # services call on_wait from the worker thread
            s.stop = stop  # reset on every run, so a set event never leaks into the next one
            s.on_wait = lambda host, sec: w.progress.emit(f"Ожидание {host}: {ceil(sec)} с", 0, 0)
        w.progress.connect(self._progress)
        w.done.connect(self._done)
        w.failed.connect(self._failed)
        self._busy(True)
        self._progress(text, 0, 0)
        w.start()

    def _login(self, text, fn, on_done=lambda _: None):
        stop = threading.Event()
        self._run(text, lambda _: fn(stop), on_done, stop)

    def _busy(self, on):
        self.centralWidget().setEnabled(not on)
        self.update_btn.setEnabled(not on)  # in the status bar, outside the central widget
        self.bar.setVisible(on)
        self.cancel_btn.setVisible(on and self.stop is not None)
        self.cancel_btn.setEnabled(True)

    @Slot(str, int, int)
    def _progress(self, text, done, total):  # total 0 = indeterminate (login, waits)
        self.status.setText(f"{text}: {done} из {total}" if total else text)
        self.bar.setRange(0, total)
        self.bar.setValue(done)

    @Slot(object)
    def _done(self, result):
        cb = self.on_done
        self._busy(False)
        self.status.clear()
        cb(result)
        self._refresh()

    @Slot(str)
    def _failed(self, text):
        self._busy(False)
        self.status.setText("Ошибка")
        self._refresh()  # rows are correct behind the dialog
        QMessageBox.warning(self, "Ошибка", text)

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            ask = QMessageBox.question(self, "Выход", "Операция ещё идёт. Прервать её и выйти? "
                                       "Если сейчас создаётся плейлист, он может остаться неполным.")
            if ask != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            # a running QThread at interpreter exit aborts the process (0xC0000409); «Отмена» is no substitute: not every run
            # has one, and it waits for the request in flight and the playlist being written
            os._exit(1)

    # --- accounts and pickers ---

    def _restore_all(self, _):
        errors = []
        for s in self.services:
            try:
                s.restore()
            except AppError as e:
                errors.append(f"{s.name}: {e}")
        if errors:
            raise AppError("\n\n".join(errors))

    def _refresh(self):
        for svc, status, btn in ((self.spotify, self.sp_status, self.sp_btn), (self.spotify2, self.sp2_status, self.sp2_btn),
                                 (self.yandex, self.ya_status, self.ya_btn), (self.yandex2, self.ya2_status, self.ya2_btn)):
            on = svc is not None and svc.connected
            status.setText((f"подключён · {svc.account}" if svc.account else "подключён") if on else "не подключён")
            btn.setText("Выйти" if on else "Войти")
            _restyle(status, "on", on)
            _restyle(btn, "accent", not on)  # green = the next thing to press
        for key, first, second, row, more in (("sp", self.spotify, self.spotify2, self.sp2_row, self.sp_more),
                                              ("ya", self.yandex, self.yandex2, self.ya2_row, self.ya_more)):
            show = second is not None and (second.connected or key in self.opened)  # key: the «+ второй» link's href
            for w in row:
                w.setVisible(show)
            more.setVisible(not show and first is not None and first.connected)
        self.sp2_help.setVisible(not self.sp2_btn.isHidden() and not self.spotify2.connected)
        if self.guide2 and self.spotify2.connected:
            self.guide2.close()  # done: the second account is in
        self.sp_id.setVisible(self.spotify is None)
        self.sp_hint.setVisible(self.spotify is None)
        self.token.setEnabled(not self.yandex.connected)
        self.alt.setVisible(not self.yandex.connected)
        if self.yandex.connected and not self.token.isHidden():
            self._toggle_token()  # the token field is done once Yandex is connected
        on = [s for s in self.services if s.connected]
        _fill(self.src, on)
        src = self.src.currentData()
        _fill(self.dst, [s for s in on if s is not src])
        pair = (src, self.dst.currentData())
        if pair != self.pair:
            self.pair = pair
            self._invalidate()
            self._sync_followed()
        if src is not self.loaded:
            self._load_playlists()
        self._update_buttons()

    def _second_click(self, svc):
        if svc.connected:
            svc.disconnect()
            self._refresh()
            return
        first = self.spotify if svc is self.spotify2 else self.yandex
        if svc is self.spotify2:
            text, login = SP_WAIT, lambda stop: svc.connect(stop=stop)
        else:
            text, login = "Получение кода входа Яндекса…", lambda stop: svc.login(self.code_ready.emit, stop)

        def work(stop):
            if login(stop) and first.connected and svc.account_id == first.account_id:
                svc.disconnect()  # the browser was still logged in to the first account
                raise AppError("Это тот же аккаунт, что уже подключён выше. Войдите во второй аккаунт: у Spotify нажмите "
                               "«Не вы?» на странице входа, у Яндекса переключите аккаунт на странице с кодом.")
        self._login(text, work)

    def _spotify_click(self):
        s = self.spotify
        if s is None:  # no client ID yet: the one typed in is saved only after a successful login
            cid = self.sp_id.text().strip()
            try:
                s = SpotifyService(cid)
            except AppError as e:
                QMessageBox.warning(self, "Ошибка", str(e))
                return
            self._login(SP_WAIT, lambda stop: s.connect(stop=stop), lambda ok: ok and self._spotify_added(s, cid))
        elif s.connected:
            s.disconnect()
            self._refresh()
        else:
            self._login(SP_WAIT, lambda stop: s.connect(stop=stop))

    def _show_guide(self):
        if self.guide is None:
            self.guide = SpotifyGuide(self)
        self.guide.show()
        self.guide.raise_()
        self.guide.activateWindow()

    def _show_second_guide(self):
        if self.guide2 is None:
            self.guide2 = SecondAccountGuide(self)
        self.guide2.show()
        self.guide2.raise_()
        self.guide2.activateWindow()

    def _open_second(self, key):
        """«+ второй аккаунт …»: show its row; a second Spotify account first needs the owner's User Management."""
        self.opened.add(key)
        self._refresh()
        if key == "sp":
            self._show_second_guide()

    def _clipboard_changed(self):
        """A client ID copied anywhere (the Dashboard page) goes straight into the field while Spotify is not set up."""
        text = QApplication.clipboard().text().strip()
        if self.spotify is None and CLIENT_ID.fullmatch(text) and self.sp_id.text().strip() != text:
            self.sp_id.setText(text)
            if self.guide:
                self.guide.close()
            if self.centralWidget().isEnabled():  # a running login keeps its own status text
                self.status.setText("Client ID подставлен из буфера обмена — нажмите «Войти» у Spotify")

    def _spotify_added(self, s, cid):
        self.spotify, self.spotify2 = s, SpotifyService(cid, 2)
        self.services[:0] = [s, self.spotify2]
        try:
            save_config({"spotify_client_id": cid})
        except AppError as e:
            QMessageBox.warning(self, "Ошибка", f"Вход выполнен, но Client ID не сохранён: {e}")

    def _yandex_click(self):
        if self.yandex.connected:
            self.yandex.disconnect()
            self._refresh()
        elif self.token.isHidden() or not self.token.text().strip():
            self._login("Получение кода входа Яндекса…", lambda stop: self.yandex.login(self.code_ready.emit, stop))
        else:
            text = self.token.text()
            self._run("Подключение к Яндекс Музыке…", lambda _: self.yandex.connect(text), lambda _: self.token.clear())

    @Slot(str, str)
    def _show_code(self, code, url):
        QApplication.clipboard().setText(code)
        self.status.setText(f'Код <b>{code}</b> скопирован: вставьте его на <a href="{url}">странице Яндекса</a> '
                            "и подтвердите вход нужным аккаунтом. Ждём…")

    def _toggle_token(self):
        show = self.token.isHidden()
        self.token.setVisible(show)
        self.ya_hint.setVisible(show)

    # --- playlists, selection, find, transfer ---

    def _load_playlists(self):
        self.loaded = src = self.src.currentData()  # set first, so a failed load is not retried in a loop by _refresh
        self.list.clear()
        self.playlists = []
        self._invalidate()
        if src:
            self._run("Загрузка плейлистов…", lambda _: src.playlists(), self._show_playlists)

    def _show_playlists(self, pls):
        self.playlists = pls
        for p in sorted(pls, key=lambda p: p.followed):  # own first, then subscriptions under their header
            if p.followed and not self.list.findItems(FOLLOW_HEAD, Qt.MatchFlag.MatchExactly):
                head = QListWidgetItem(FOLLOW_HEAD)
                head.setFlags(Qt.ItemFlag.NoItemFlags)
                head.setToolTip("Отмеченные появятся в медиатеке аккаунта «Куда» как подписка, а не копия")
                self.list.addItem(head)
            item = QListWidgetItem(f"{p.name} ({p.count})")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.list.addItem(item)
        self._sync_followed()

    def _same_service(self):
        src, dst = self.src.currentData(), self.dst.currentData()
        return bool(src and dst and src.name == dst.name)

    def _sync_followed(self):
        """Subscriptions are only offered between two accounts of the same service; hidden ones are never picked."""
        same = self._same_service()
        for r in range(self.list.count()):
            p = self.list.item(r).data(Qt.ItemDataRole.UserRole)
            if p is None or p.followed:  # the header or a subscription
                self.list.item(r).setHidden(not same)

    def _checked(self):
        items = (self.list.item(r) for r in range(self.list.count()))
        return [i.data(Qt.ItemDataRole.UserRole) for i in items
                if not i.isHidden() and i.checkState() == Qt.CheckState.Checked]

    def _check_all(self, state):
        for r in range(self.list.count()):
            p = self.list.item(r).data(Qt.ItemDataRole.UserRole)
            if p and (state == Qt.CheckState.Unchecked or not p.followed):  # subscriptions are picked one by one
                self.list.item(r).setCheckState(state)

    def _mode_changed(self, merged):
        self.name.setPlaceholderText(MERGED_NAME if merged else PER_NAME)
        self._invalidate()

    def _invalidate(self):
        self.jobs = self.follows = None
        self.followed_done = False
        self.rows = []
        self.table.setRowCount(0)
        self._update_buttons()

    def _update_buttons(self):
        ready = bool(self.dst.currentText() and self._checked() and (self.per.isChecked() or self.name.text().strip()))
        pending = any(j.added is None for j in self.jobs or []) or bool(self.follows and not self.followed_done)
        self.find_btn.setEnabled(ready)
        self.go_btn.setEnabled(ready and pending)
        self.csv_btn.setEnabled(bool(self.jobs and any(j.not_found() for j in self.jobs)))
        self.reload.setEnabled(bool(self.src.currentText()))

    def _show(self, headers, rows):
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))

    def _find(self):
        src, dst, same = self.src.currentData(), self.dst.currentData(), self._same_service()
        chosen = self._checked()
        own, follows = [p for p in chosen if not p.followed], [p for p in chosen if p.followed]
        name = self.name.text().strip() if self.merged.isChecked() else None

        def work(progress):
            jobs = build_jobs(src, own, name, lambda d, n: progress("Чтение плейлистов", d, n)) if own else []
            if same:  # another account of the same service: the very same tracks, no search
                copy_jobs(jobs)
            else:
                match_jobs(jobs, dst, lambda d, n: progress("Поиск треков", d, n))
            return jobs, follows, own
        self._run("Чтение плейлистов…" if same else "Поиск треков…", work, self._found, threading.Event())

    def _found(self, result):
        if result is None:  # «Отмена»: partial matches are dropped, nothing was written
            self._invalidate()
            self.status.setText("Отменено. В аккаунты ничего не записано.")
            return
        self.jobs, self.follows, self.own = result
        self.followed_done = False
        self.rows = [(j, i) for j in self.jobs for i in range(len(j.results))]  # table row -> result, for _pick
        # shortcut: QTableWidget filled on the UI thread; fine for a few thousand rows, switch to a model if it stalls
        self._show(["Плейлист", "Исходный трек", "Найдено", "Способ"],
                   [self._row(j, i) for j, i in self.rows]
                   + [(p.name, "чужой плейлист", "подписаться", "подписка") for p in self.follows])
        self._count()

    def _row(self, job, i):
        s, f, how = job.results[i]
        return job.name, _fmt(s), _fmt(f) if f else "не найдено", how

    def _count(self):
        total = sum(len(j.results) for j in self.jobs)
        found = sum(f is not None for j in self.jobs for _, f, _ in j.results)
        follows = f" Подписок: {len(self.follows)}." if self.follows else ""
        hint = " Двойной щелчок по строке — выбрать трек вручную." if found < total else ""
        clean = " В аккаунты ничего не записано." if all(j.added is None for j in self.jobs) else ""  # after a failed transfer
        self.status.setText(f"Найдено {found} из {total}.{follows}{hint}{clean}")

    def _pick(self, row, query=None):
        """Double-click on a result row: search the target for that track in the worker, then PickDialog."""
        if row >= len(self.rows):  # a subscription, or the summary after a transfer
            return
        job, i = self.rows[row]
        if job.added is not None:  # written by a transfer that failed later: existing playlists are never touched
            self.status.setText(f"Плейлист «{job.name}» уже создан — его треки не меняются.")
            return
        src, dst = job.results[i][0], self.dst.currentData()
        artist, title = query or ((src.artists or [""])[0], src.title)  # the matcher's query first

        def work(progress):
            found = dst.search(artist, strip_tags(title)) if artist or title else []
            progress("Поиск вариантов", 0, 0)  # raises Cancelled if «Отмена» came during the request
            if found or not (artist and title):
                return found, artist
            found = dst.search("", strip_tags(title))  # the target may credit someone else (seen live: a soundtrack)
            progress("Поиск вариантов", 0, 0)
            return found, "" if found else artist  # the dialog shows the query that gave its list
        self._run("Поиск вариантов…", work,
                  lambda r: self._count() if r is None else self._show_pick(row, r[1], title, r[0]),
                  threading.Event())  # «Отмена» leaves the status empty, so restore it

    def _show_pick(self, row, artist, title, found):
        job, i = self.rows[row]
        self.picker = d = PickDialog(self, job.results[i][0], artist, title, found)
        d.finished.connect(lambda code: self._picked(row, d, code))
        self._count()
        d.open()  # window-modal and returns at once: no nested event loop

    def _picked(self, row, d, code):
        if code == SEARCH:
            self._pick(row, (d.artist.text().strip(), d.title.text().strip()))
            return
        if code not in (PICK, SKIP):  # «Отмена», Esc, the close button
            return
        job, i = self.rows[row]
        found = d.picked() if code == PICK else None
        k, how = track_key(job.results[i][0]), "вручную" if found else ""
        for r, (j, n) in enumerate(self.rows):  # the same source track elsewhere gets the same pick, as in match_jobs
            if j.added is None and track_key(j.results[n][0]) == k:
                j.results[n] = (j.results[n][0], found, how)
                for c, v in enumerate(self._row(j, n)):
                    self.table.item(r, c).setText(v)
        self._count()
        self._update_buttons()  # the CSV button follows not_found()

    def _transfer(self):
        jobs, follows, dst, done = self.jobs, self.follows, self.dst.currentData(), self.followed_done
        name = self.name.text().strip()  # read now: it may have been edited after matching
        if self.merged.isChecked() and jobs:
            jobs[0].name = name
        elif name:
            for job, p in zip(jobs, self.own):
                if p.id == LIKED:
                    job.name = name  # per-playlist mode: the liked tracks go to a playlist the user named

        def work(progress):
            write_jobs(jobs, dst, lambda d, n: progress("Создание плейлистов", d, n))
            for i, p in enumerate([] if done else follows):  # a repeated follow is harmless, so a rerun does them all
                progress("Подписки", i, len(follows))  # before the follow: «Отмена» during the last one is not a cancel
                dst.follow(p)
            return True
        steps = sum(j.added is None for j in jobs) + (0 if done else len(follows))
        self._run("Создание плейлистов…", work, lambda ok: self._written(dst, ok),
                  threading.Event() if steps > 1 else None,  # a started playlist is never cut: one step has nothing to stop
                  "Остановка: начатый плейлист допишется, следующие не начнутся.")

    def _written(self, dst, ok):
        """ok is None after «Отмена»: written jobs keep `added`, so «Перенести» goes on with the rest."""
        self.rows = []  # the table is the summary now: nothing to pick
        if ok is None and all(j.added is not None for j in self.jobs) and not self.follows:
            ok = True  # «Отмена» came during the last playlist: everything is written
        self.followed_done = bool(ok)
        self._show(["Плейлист", "Добавлено", "Не найдено"],
                   [(j.name, "не создан" if j.added is None else j.added, len(j.not_found())) for j in self.jobs]
                   + [(p.name, "подписка оформлена" if ok else "не завершено", "") for p in self.follows])
        if ok:
            follows = f", подписок — {len(self.follows)}" if self.follows else ""
            text = f"Готово ({dst.label}): новых плейлистов — {len(self.jobs)}{follows}."
        else:
            made = sum(j.added is not None for j in self.jobs)
            text = (f"Отменено ({dst.label}): новых плейлистов — {made} из {len(self.jobs)}. "
                    "«Перенести» продолжит с оставшихся.")
        self.status.setText(f"{text} Существующие плейлисты не изменялись.")

    # --- updates: the latest GitHub release's installer, run silently; it restarts the app ---

    def _check_update(self):
        self._run("Проверка обновлений…", lambda _: update.latest(), self._update_found)

    def _update_found(self, found):
        version, asset = found
        if not update.is_newer(version):
            self.status.setText(f"У вас последняя версия ({__version__})")
            return
        if not getattr(sys, "frozen", False):
            self.status.setText(f"Вышла версия {version}. Из исходников обновление не ставится: git pull или build.ps1")
            return
        ask = QMessageBox.question(self, "Обновление", f"Вышла версия {version} (у вас {__version__}). Установить? "
                                   "Программа закроется и через несколько секунд откроется уже новой.")
        if ask == QMessageBox.StandardButton.Yes:
            mb = 1 << 20
            self._run("Загрузка обновления…",
                      lambda p: update.download(asset, lambda d, n: p("Загрузка обновления, МБ", d // mb, n // mb)),
                      self._install_update)

    def _install_update(self, path):
        update.install(path)
        QApplication.quit()

    def _save_csv(self):
        docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить ненайденные треки",
                                              os.path.join(docs, "ненайденные.csv"), "CSV (*.csv)")
        if not path:
            return
        try:
            export_csv(path, self.jobs)
        except OSError as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить файл: {e}")
            return
        self.status.setText(f"Сохранено: {path}")


def run():
    app = QApplication(sys.argv)
    update.cleanup()
    theme.apply(app)
    w = MainWindow()
    theme.dark_title_bar(w)
    w.show()
    sys.exit(app.exec())
