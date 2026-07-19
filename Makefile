PREFIX ?= /usr
BINDIR := $(DESTDIR)$(PREFIX)/bin

.PHONY: install uninstall check

install:
	install -Dm755 pacmangr "$(BINDIR)/pacmangr"

uninstall:
	rm -f "$(BINDIR)/pacmangr"

check:
	python3 -m py_compile pacmangr
	python3 -m unittest discover -s tests -v
	./pacmangr --version
	./pacmangr --list-managers
	./pacmangr --help
	./pacmangr doctor
