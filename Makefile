PREFIX ?= /usr
BINDIR := $(DESTDIR)$(PREFIX)/bin

.PHONY: install uninstall check

install:
	install -Dm755 pacmangr "$(BINDIR)/pacmangr"

uninstall:
	rm -f "$(BINDIR)/pacmangr"

check:
	python3 -m py_compile pacmangr
	./pacmangr --version
	./pacmangr --list-managers
