import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # offscreen Qt on Windows has no fonts: every glyph is a box

import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from music_transfer import gui
from music_transfer.common import APP_DIR, CONFIG_PATH, LIKED, Playlist, Track
from music_transfer.matching import strip_tags

app = QApplication.instance() or QApplication([])


class Fake:
    """Stands for a service; records whether each network-like call ran on the main thread."""
    def __init__(self, name, playlists, tracks, catalog, account=None, restored=True):
        self.name, self._playlists, self._tracks, self.catalog = name, playlists, tracks, catalog
        self.connected, self.on_wait, self.on_main = False, None, []
        self.created, self.followed, self.fail_on, self._n, self.hold = [], [], None, 0, False
        self.account, self.account_id, self.restored = account, account or name, restored

    @property
    def label(self):
        return f"{self.name} · {self.account}" if self.account else self.name

    def _net(self):
        self.on_main.append(threading.current_thread() is threading.main_thread())

    def restore(self):
        self._net()
        self.connected = self.restored
        return self.restored

    def follow(self, p):
        self._net()
        self.followed.append(p.id)

    def connect(self, *a, stop=None):
        self._net()
        if self.hold:  # a login the user never finishes: only «Отмена» ends it
            assert stop.wait(10)
            return False
        self.connected = True
        return True

    def login(self, on_code, stop):
        on_code("ABCD-1234", "https://ya.ru/device")
        return self.connect(stop=stop)

    def disconnect(self):
        self.connected = False

    def playlists(self):
        self._net()
        return self._playlists

    def tracks(self, p):
        self._net()
        return self._tracks[p.id]

    def search_isrc(self, isrc):
        self._net()
        return []

    def search(self, artist, title):
        self._net()
        return [t for t in self.catalog if strip_tags(t.title) == title]

    def create_playlist(self, name, tracks):
        self._net()
        self._n += 1
        if self.fail_on == self._n:
            raise RuntimeError("boom")
        self.created.append((name, [t.id for t in tracks]))
        return "id"


def settle(w, timeout=10):
    """Wait until the window is idle again (restore chains into the playlist load)."""
    for _ in range(timeout * 100):
        QTest.qWait(10)
        if w.centralWidget().isEnabled():
            break
    assert w.centralWidget().isEnabled(), "worker did not finish"
    w.worker.wait()


def T(id, title, artist="Artist"):
    return Track(id, title, [artist], 200000)


def make_fakes():
    s1, s2, s3 = T("s1", "Группа крови", "Кино"), T("s2", "Unknown Song"), T("s3", "Another Song")
    sp = Fake("Spotify", [Playlist(LIKED, "Любимые треки", 2), Playlist("p", "P", 1)],
              {LIKED: [s1, s2], "p": [s3]}, [])
    ya = Fake("Яндекс Музыка", [Playlist(LIKED, "Мне нравится", 1), Playlist("9", "Яндекс-плейлист", 0)],
              {LIKED: [T("y5", "Песня", "Земфира")], "9": []},
              [T("y1", "Группа крови", "Кино"), T("y3", "Another Song")])
    return sp, ya


def second(name):
    """The second account of a service: nothing saved, so it starts logged out."""
    return Fake(name, [], {}, [], account="new", restored=False)


def slots(first, second):
    """Stands for SpotifyService(cid, slot) / YandexService(slot): slot 2 is the second account."""
    return lambda *a: second if a and a[-1] == 2 else first


@pytest.fixture(autouse=True)
def saved(monkeypatch):
    out = []
    monkeypatch.setattr(gui, "save_config", out.append)  # never the real config.json next to the app
    return out


@pytest.fixture
def dialogs(monkeypatch):
    shown = []
    monkeypatch.setattr(gui.QMessageBox, "warning", lambda *a: shown.append(a[2]))
    return shown


@pytest.fixture
def services(monkeypatch, dialogs):
    sp, ya = make_fakes()
    monkeypatch.setattr(gui, "load_config", lambda: {"spotify_client_id": "cid"})
    monkeypatch.setattr(gui, "SpotifyService", slots(sp, second("Spotify")))
    monkeypatch.setattr(gui, "YandexService", slots(ya, second("Яндекс Музыка")))
    return sp, ya


def window():
    w = gui.MainWindow()
    settle(w)
    return w


def tick_all(w):
    for r in range(w.list.count()):
        w.list.item(r).setCheckState(Qt.CheckState.Checked)


def column(w, c):
    return [w.table.item(r, c).text() for r in range(w.table.rowCount())]


def wait_for(cond, timeout=10):
    for _ in range(timeout * 100):
        QTest.qWait(10)
        if cond():
            return
    raise AssertionError("condition not reached")


def test_starts_clean_without_config_or_tokens(monkeypatch, dialogs, saved):
    monkeypatch.setattr(gui, "load_config", lambda: {})
    for f in ("yandex.json", "spotify.json", "yandex-2.json", "spotify-2.json"):  # a stray token would go to the network
        (APP_DIR / f).unlink(missing_ok=True)
    w = window()
    assert w.sp_status.text() == "не подключён" and w.sp_btn.text() == "Войти" and w.sp_btn.isEnabled()
    assert not w.sp_id.isHidden() and not w.sp_hint.isHidden() and w.token.isHidden()
    assert w.ya_status.text() == "не подключён" and w.src.count() == 0
    assert not (w.find_btn.isEnabled() or w.go_btn.isEnabled() or w.csv_btn.isEnabled())
    assert dialogs == []
    w.sp_id.setText("abc")  # the real SpotifyService validates before any login
    w.sp_btn.click()
    assert "32 символа" in dialogs[-1] and w.centralWidget().isEnabled() and saved == []


def test_broken_config_is_shown_next_to_the_client_id_field(monkeypatch, dialogs):
    def broken():
        raise gui.AppError("config.json повреждён: x")
    monkeypatch.setattr(gui, "load_config", broken)
    monkeypatch.setattr(gui, "YandexService", slots(make_fakes()[1], second("Яндекс Музыка")))
    w = window()
    assert "config.json повреждён: x" in w.sp_hint.text() and str(CONFIG_PATH) in w.sp_hint.text()
    assert not w.sp_id.isHidden() and dialogs == []


def test_client_id_typed_in_logs_in_then_is_saved(monkeypatch, dialogs, saved):
    sp, ya = make_fakes()
    cid, made = "0123456789abcdef0123456789abcdef", []
    monkeypatch.setattr(gui, "load_config", lambda: {})
    monkeypatch.setattr(gui, "SpotifyService", lambda c, slot=1: (made.append(c) or sp) if slot == 1 else second("Spotify"))
    monkeypatch.setattr(gui, "YandexService", slots(ya, second("Яндекс Музыка")))
    w = window()
    assert [w.src.itemText(i) for i in range(w.src.count())] == ["Яндекс Музыка"]
    sp.hold = True  # first try: the user gives up in the browser
    w.sp_id.setText(f" {cid} ")
    w.sp_btn.click()
    wait_for(lambda: not w.cancel_btn.isHidden())
    w.cancel_btn.click()
    settle(w)
    assert saved == [] and not w.sp_id.isHidden() and w.cancel_btn.isHidden() and dialogs == []
    sp.hold = False
    w.sp_btn.click()
    settle(w)
    assert made == [cid, cid] and saved == [{"spotify_client_id": cid}] and sp.connected
    assert w.sp_id.isHidden() and w.sp_btn.text() == "Выйти"
    assert w.sp_status.property("on") is True and w.sp_btn.property("accent") is False  # green moves on
    assert [w.src.itemText(i) for i in range(w.src.count())] == ["Spotify", "Яндекс Музыка"]
    assert not any(sp.on_main) and dialogs == []


def test_guide_copies_form_values_and_a_copied_client_id_fills_the_field(monkeypatch, dialogs):
    cid, opened = "0123456789abcdef0123456789abcdef", []
    monkeypatch.setattr(gui, "load_config", lambda: {})
    monkeypatch.setattr(gui, "YandexService", slots(make_fakes()[1], second("Яндекс Музыка")))
    monkeypatch.setattr(gui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    w = window()
    w.sp_hint.linkActivated.emit("#guide")
    g = w.guide
    assert not g.isHidden()
    g.open_btn.click()
    assert opened == [gui.CREATE_APP_URL]
    copy = [b for b in g.findChildren(gui.QPushButton) if b.text() == "Копировать"]
    assert len(copy) == len(gui.APP_FORM)
    copy[-1].click()
    assert QApplication.clipboard().text() == gui.REDIRECT_URI and copy[-1].text() == "Скопировано"
    assert w.sp_id.text() == ""  # not an ID
    QApplication.clipboard().setText(f" {cid}\n")
    wait_for(lambda: w.sp_id.text() == cid)
    assert g.isHidden() and "Войти" in w.status.text() and dialogs == []


def test_copied_client_id_is_ignored_once_spotify_is_set_up(services):
    w = window()
    QApplication.clipboard().setText("0123456789abcdef0123456789abcdef")
    QTest.qWait(50)
    assert w.sp_id.text() == "" and w.guide is None


def test_moving_to_a_second_account_copies_tracks_and_follows_picked_subscriptions(monkeypatch, dialogs):
    sp, ya = make_fakes()
    sp._playlists = sp._playlists + [Playlist("f1", "Чужой", 10, followed=True)]
    sp2 = second("Spotify")
    monkeypatch.setattr(gui, "load_config", lambda: {"spotify_client_id": "cid"})
    monkeypatch.setattr(gui, "SpotifyService", slots(sp, sp2))
    monkeypatch.setattr(gui, "YandexService", slots(ya, second("Яндекс Музыка")))
    opened = []
    monkeypatch.setattr(gui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    w = window()
    assert w.sp2_btn.isHidden() and w.sp2_help.isHidden() and not w.sp_more.isHidden()
    w.sp_more.linkActivated.emit("sp")
    assert not w.sp2_btn.isHidden() and w.sp_more.isHidden() and not w.sp2_help.isHidden()
    g2 = w.guide2  # a second Spotify account must be in the app's User Management first
    assert not g2.isHidden() and any("developer.spotify.com/dashboard</a>" in l.text() for l in g2.findChildren(gui.QLabel))
    g2.open_btn.click()
    assert opened == [gui.DASHBOARD_URL]
    g2.close()
    w.sp2_help.linkActivated.emit("#")
    assert not g2.isHidden()
    w.sp2_btn.click()
    settle(w)
    assert sp2.connected and w.sp2_status.text() == "подключён · new" and g2.isHidden() and w.sp2_help.isHidden()
    assert [w.dst.itemText(i) for i in range(w.dst.count())] == ["Spotify · new", "Яндекс Музыка"]
    w.dst.setCurrentIndex(0)
    w.dst.activated.emit(0)
    assert [w.list.item(r).text() for r in range(w.list.count())] == \
        ["Любимые треки (2)", "P (1)", gui.FOLLOW_HEAD, "Чужой (10)"]
    w._check_all(Qt.CheckState.Checked)
    assert w.list.item(3).checkState() == Qt.CheckState.Unchecked  # subscriptions are not ticked by «Выбрать все»
    w.list.item(3).setCheckState(Qt.CheckState.Checked)
    w.name.setText("Старое")
    w.find_btn.click()
    settle(w)
    assert column(w, 3) == ["копия", "копия", "копия", "подписка"]
    w.table.activated.emit(w.table.model().index(3, 0))  # a subscription row has nothing to pick
    assert w.centralWidget().isEnabled()
    w.go_btn.click()
    settle(w)
    assert sp2.created == [("Старое", ["s1", "s2"]), ("P", ["s3"])] and sp2.followed == ["f1"]
    assert sp.created == [] and not w.go_btn.isEnabled() and not any(sp2.on_main) and dialogs == []
    w.dst.setCurrentIndex(1)  # another service: subscriptions cannot be passed there
    w.dst.activated.emit(1)
    assert w.list.item(2).isHidden() and w.list.item(3).isHidden() and len(w._checked()) == 2


def test_second_login_into_the_same_account_is_refused(monkeypatch, dialogs):
    sp, ya = make_fakes()
    ya2 = second("Яндекс Музыка")
    ya.account_id = ya2.account_id = "uid-1"
    monkeypatch.setattr(gui, "load_config", lambda: {"spotify_client_id": "cid"})
    monkeypatch.setattr(gui, "SpotifyService", slots(sp, second("Spotify")))
    monkeypatch.setattr(gui, "YandexService", slots(ya, ya2))
    w = window()
    w.ya_more.linkActivated.emit("ya")
    w.ya2_btn.click()
    settle(w)
    assert not ya2.connected and "тот же аккаунт" in dialogs[-1] and w.dst.count() == 1


def test_update_button_installs_a_newer_release_and_quits(services, monkeypatch):
    w = window()
    assert gui.__version__ in w.windowTitle()
    monkeypatch.setattr(gui.update, "latest", lambda: (gui.__version__, {}))
    w.update_btn.click()
    settle(w)
    assert "последняя версия" in w.status.text()
    calls = []
    monkeypatch.setattr(gui.update, "latest", lambda: ("999.0.0", {"size": 1}))
    monkeypatch.setattr(gui.update, "download", lambda a, progress: calls.append(("download", a)) or "setup.exe")
    monkeypatch.setattr(gui.update, "install", lambda path: calls.append(("install", path)))
    monkeypatch.setattr(gui.QApplication, "quit", lambda: calls.append(("quit",)))
    monkeypatch.setattr(gui.QMessageBox, "question", lambda *a: gui.QMessageBox.StandardButton.Yes)
    w.update_btn.click()
    settle(w)
    assert "999.0.0" in w.status.text() and calls == []  # from sources nothing is installed
    monkeypatch.setattr(gui.sys, "frozen", True, raising=False)
    w.update_btn.click()
    settle(w)
    assert calls == [("download", {"size": 1}), ("install", "setup.exe"), ("quit",)]


def test_yandex_login_shows_and_copies_the_code_and_can_be_cancelled(services, dialogs):
    sp, ya = services
    w = window()
    w.ya_btn.click()  # disconnect
    assert not ya.connected and w.ya_btn.text() == "Войти"
    ya.hold = True
    w.ya_btn.click()
    wait_for(lambda: "ABCD-1234" in w.status.text())
    assert QApplication.clipboard().text() == "ABCD-1234" and "https://ya.ru/device" in w.status.text()
    assert not w.cancel_btn.isHidden() and not w.centralWidget().isEnabled()
    w.cancel_btn.click()
    settle(w)
    assert not ya.connected and w.cancel_btn.isHidden()
    assert w.ya_btn.property("accent") is True and not w.alt.isHidden()
    ya.hold = False
    w.ya_btn.click()
    settle(w)
    assert ya.connected and not any(ya.on_main) and dialogs == []
    assert w.alt.isHidden() and w.ya_btn.property("accent") is False


def test_pasted_token_is_the_fallback(services):
    sp, ya = services
    w = window()
    w.ya_btn.click()
    calls = []
    ya.login = lambda *a: calls.append("login")
    ya.connect = lambda text: calls.append(text)
    alt = next(l for l in w.findChildren(gui.QLabel) if "Другой способ" in l.text())
    alt.linkActivated.emit("#")
    assert not w.token.isHidden() and not w.ya_hint.isHidden()
    w.token.setText("tok")
    w.ya_btn.click()
    settle(w)
    assert calls == ["tok"] and w.token.text() == ""


def test_find_shows_matches_then_transfer_creates_new_playlists(services, dialogs, monkeypatch, tmp_path):
    sp, ya = services
    w = window()
    assert [w.src.itemText(i) for i in range(w.src.count())] == ["Spotify", "Яндекс Музыка"]
    assert [w.dst.itemText(i) for i in range(w.dst.count())] == ["Яндекс Музыка"]
    assert [w.list.item(r).text() for r in range(w.list.count())] == ["Любимые треки (2)", "P (1)"]
    tick_all(w)
    w.find_btn.click()
    settle(w)
    assert column(w, 2) == ["Кино — Группа крови", "не найдено", "Artist — Another Song"]
    assert column(w, 3) == ["поиск", "", "поиск"]
    assert ya.created == [] and w.go_btn.isEnabled() and w.csv_btn.isEnabled()
    ya.on_wait("api.music.yandex.net", 4.2)
    assert w.status.text() == "Ожидание api.music.yandex.net: 5 с"
    w.go_btn.click()
    settle(w)
    assert ya.created == [("Любимые треки", ["y1"]), ("P", ["y3"])]
    assert [w.table.horizontalHeaderItem(c).text() for c in range(3)] == ["Плейлист", "Добавлено", "Не найдено"]
    assert [column(w, c) for c in range(3)] == [["Любимые треки", "P"], ["1", "1"], ["1", "0"]]
    assert not w.go_btn.isEnabled()
    out = tmp_path / "nf.csv"
    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    w.csv_btn.click()
    assert out.read_bytes().startswith(b"\xef\xbb\xbf") and "Unknown Song" in out.read_text(encoding="utf-8-sig")
    assert not any(sp.on_main + ya.on_main) and dialogs == []


def test_changes_invalidate_results_and_merged_name_is_read_at_write(services):
    sp, ya = services
    w = window()
    tick_all(w)
    w.find_btn.click()
    settle(w)
    assert w.table.rowCount() == 3
    w.list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert w.table.rowCount() == 0 and not w.go_btn.isEnabled()
    w.list.item(1).setCheckState(Qt.CheckState.Checked)
    w.merged.setChecked(True)
    assert w.table.rowCount() == 0 and not w.find_btn.isEnabled()
    w.name.setText("Все")
    w.find_btn.click()
    settle(w)
    w.name.setText("Все треки")
    w.go_btn.click()
    settle(w)
    assert ya.created == [("Все треки", ["y1", "y3"])]
    w.src.setCurrentIndex(1)
    w.src.activated.emit(1)
    settle(w)
    assert [w.dst.itemText(i) for i in range(w.dst.count())] == ["Spotify"]
    assert [w.list.item(r).text() for r in range(w.list.count())] == ["Мне нравится (1)", "Яндекс-плейлист (0)"]


def test_failed_transfer_reports_and_rerun_skips_written(services, dialogs):
    sp, ya = services
    w = window()
    tick_all(w)
    w.find_btn.click()
    settle(w)
    ya.fail_on = 2
    w.go_btn.click()
    settle(w)
    assert "«P»" in dialogs[-1] and "1 из 2" in dialogs[-1] and w.go_btn.isEnabled()
    w.table.activated.emit(w.table.model().index(0, 0))  # that playlist exists already: its tracks are not picked again
    assert "уже создан" in w.status.text() and w.centralWidget().isEnabled()
    ya.fail_on = None
    w.go_btn.click()
    settle(w)
    assert [n for n, _ in ya.created] == ["Любимые треки", "P"]


def test_find_can_be_cancelled_and_drops_its_results(services, dialogs):
    sp, ya = services
    w = window()
    tick_all(w)
    searched, real = [], ya.search

    def search(artist, title):
        searched.append(title)
        assert w.stop.wait(10)  # held until «Отмена»
        return real(artist, title)
    ya.search = search
    w.find_btn.click()
    assert not w.cancel_btn.isHidden() and w.cancel_btn.isEnabled()
    wait_for(lambda: searched)
    w.cancel_btn.click()
    assert not w.cancel_btn.isEnabled()
    settle(w)
    assert len(searched) == 1 and w.jobs is None and w.table.rowCount() == 0
    assert "Отменено" in w.status.text() and w.cancel_btn.isHidden() and not w.go_btn.isEnabled()
    assert ya.created == [] and dialogs == []


def test_cancelled_transfer_finishes_the_current_playlist_and_rerun_continues(services, dialogs):
    sp, ya = services
    w = window()
    tick_all(w)
    w.find_btn.click()
    settle(w)
    real = ya.create_playlist

    def create(name, tracks):
        assert w.stop.wait(10)  # held until «Отмена»
        return real(name, tracks)
    ya.create_playlist = create
    w.go_btn.click()
    w.cancel_btn.click()
    settle(w)
    assert ya.created == [("Любимые треки", ["y1"])]
    assert column(w, 1) == ["1", "не создан"]
    assert "1 из 2" in w.status.text() and w.go_btn.isEnabled() and dialogs == []
    ya.create_playlist = real
    w.go_btn.click()
    settle(w)
    assert [n for n, _ in ya.created] == ["Любимые треки", "P"] and "Готово" in w.status.text()


def test_cancel_during_the_last_playlist_reports_done(services, dialogs):
    sp, ya = services
    w = window()
    w.list.item(0).setCheckState(Qt.CheckState.Checked)
    w.find_btn.click()
    settle(w)
    real = ya.create_playlist

    def create(name, tracks):
        assert w.stop.wait(10)  # held until «Отмена»
        return real(name, tracks)
    ya.create_playlist = create
    w.go_btn.click()
    w.cancel_btn.click()
    settle(w)
    assert ya.created == [("Любимые треки", ["y1"])]
    assert "Готово" in w.status.text() and "Отменено" not in w.status.text()
    assert not w.go_btn.isEnabled() and dialogs == []


def test_a_miss_is_picked_by_hand_for_every_copy_of_the_track(services, dialogs):
    sp, ya = services
    sp._tracks["p"] = sp._tracks["p"] + [sp._tracks[LIKED][1]]
    # y2 is too long for the matcher and y9 is unavailable: the track stays a miss
    ya.catalog += [Track("y2", "Unknown Song", ["Artist"], 600000), Track("y9", "Unknown Song", ["Artist"], 200000, available=False)]
    w = window()
    tick_all(w)
    w.find_btn.click()
    settle(w)
    assert column(w, 2) == ["Кино — Группа крови", "не найдено", "Artist — Another Song", "не найдено"]
    assert "Двойной щелчок" in w.status.text()
    w.table.activated.emit(w.table.model().index(1, 0))
    settle(w)
    d = w.picker
    assert d.isVisible() and d.artist.text() == "Artist" and d.title.text() == "Unknown Song"
    assert [d.list.item(i).text() for i in range(d.list.count())] == \
        ["Artist — Unknown Song · 10:00", "Artist — Unknown Song · 3:20 · недоступен"]
    d.list.setCurrentRow(1)
    d.pick_btn.click()
    assert d.isVisible()  # an unavailable track cannot be chosen
    d.list.setCurrentRow(0)
    QTest.keyClick(d.list, Qt.Key.Key_Return)  # Enter picks, it does not search again
    assert not d.isVisible()
    assert column(w, 2)[1] == column(w, 2)[3] == "Artist — Unknown Song"
    assert column(w, 3) == ["поиск", "вручную", "поиск", "вручную"]
    assert "Найдено 4 из 4" in w.status.text() and not w.csv_btn.isEnabled()
    w.go_btn.click()
    settle(w)
    assert ya.created == [("Любимые треки", ["y1", "y2"]), ("P", ["y3", "y2"])]
    w.table.activated.emit(w.table.model().index(0, 0))  # the table is the summary now
    assert w.centralWidget().isEnabled() and w.picker is d
    assert not any(sp.on_main + ya.on_main) and dialogs == []


def test_pick_search_again_skip_cancel_and_merged_dedup(services, dialogs, monkeypatch, tmp_path):
    sp, ya = services
    w = window()
    tick_all(w)
    w.merged.setChecked(True)
    w.name.setText("Все")
    w.find_btn.click()
    settle(w)
    assert column(w, 2) == ["Кино — Группа крови", "не найдено", "Artist — Another Song"]
    real = ya.search
    ya.search = lambda a, t: (w.stop.wait(10), real(a, t))[1]  # held until «Отмена»
    w.table.activated.emit(w.table.model().index(1, 0))
    w.cancel_btn.click()
    settle(w)
    assert w.picker is None
    ya.search = real
    w.table.activated.emit(w.table.model().index(1, 0))
    settle(w)
    first = w.picker
    assert first.list.count() == 0
    first.title.setText(strip_tags("Группа крови"))
    first.search_btn.click()
    settle(w)
    d = w.picker
    assert d is not first and d.list.count() == 1
    d.list.setCurrentRow(0)
    d.pick_btn.click()
    assert column(w, 2)[1] == "Кино — Группа крови" and column(w, 3)[1] == "вручную"
    w.table.activated.emit(w.table.model().index(2, 0))
    settle(w)
    w.picker.skip_btn.click()
    assert column(w, 2)[2] == "не найдено" and column(w, 3)[2] == ""  # a wrong automatic match dropped
    w.table.activated.emit(w.table.model().index(0, 0))
    settle(w)
    w.picker.reject()
    assert column(w, 3)[0] == "поиск"
    out = tmp_path / "nf.csv"
    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    w.csv_btn.click()
    text = out.read_text(encoding="utf-8-sig")
    assert "Another Song" in text and "Unknown Song" not in text
    w.go_btn.click()
    settle(w)
    assert ya.created == [("Все", ["y1"])]
    assert not any(ya.on_main) and dialogs == []
