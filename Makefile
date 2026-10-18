PREFIX ?= /usr
BINDIR := $(DESTDIR)$(PREFIX)/bin
APPLICATIONDIR := $(DESTDIR)$(PREFIX)/share/applications
ICONDIR := $(DESTDIR)$(PREFIX)/share/icons/hicolor/512x512/apps
APP_ID := io.github.hei.pacmangr

.PHONY: install uninstall check

install:
	install -Dm755 pacmangr "$(BINDIR)/pacmangr"
	install -Dm755 pacmangr-gui "$(BINDIR)/pacmangr-gui"
	install -Dm644 $(APP_ID).desktop "$(APPLICATIONDIR)/$(APP_ID).desktop"
	install -Dm644 assets/$(APP_ID).png "$(ICONDIR)/$(APP_ID).png"
	install -Dm644 assets/pacmangr-exit.png "$(DESTDIR)$(PREFIX)/share/pacmangr/assets/pacmangr-exit.png"

uninstall:
	rm -f "$(BINDIR)/pacmangr"
	rm -f "$(BINDIR)/pacmangr-gui"
	rm -f "$(APPLICATIONDIR)/$(APP_ID).desktop"
	rm -f "$(ICONDIR)/$(APP_ID).png"
	rm -f "$(DESTDIR)$(PREFIX)/share/pacmangr/assets/pacmangr-exit.png"
	rmdir --ignore-fail-on-non-empty "$(DESTDIR)$(PREFIX)/share/pacmangr/assets" "$(DESTDIR)$(PREFIX)/share/pacmangr" 2>/dev/null || true

check:
	python3 -m py_compile pacmangr
	python3 -m py_compile pacmangr-gui
	python3 -m unittest discover -s tests -v
	./pacmangr --version
	./pacmangr-gui --version
	./pacmangr --list-managers
	./pacmangr --help
	./pacmangr doctor
