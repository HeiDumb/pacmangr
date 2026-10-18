# Maintainer: HeiDumb <rockygehlot31@gmail.com>
pkgname=pacmangr
pkgver=0.3.0
pkgrel=2
pkgdesc="Unified terminal and GTK interface for native package managers"
arch=('any')
url="https://github.com/HeiDumb/pacmangr"
license=('MIT')
depends=('python' 'python-gobject' 'gtk4' 'polkit')
optdepends=(
  'pacman: Arch repository package support'
  'yay: AUR package support'
  'paru: alternate AUR package support'
  'pacseek: interactive Arch package lookup'
  'downgrade: Arch package version history and downgrade support'
  'flatpak: Flatpak application support'
  'git: managed Git repository fetching and updates'
  'apt: Debian/Ubuntu package support'
  'snapd: Snap package support'
  'cargo: Rust crate support'
  'npm: Node package support'
  'python-pip: Python package support'
  'pipx: Python application support'
  'ruby: gem package support'
  'luarocks: Lua package support'
)

source=("pacmangr-main.tar.gz::https://github.com/HeiDumb/pacmangr/archive/refs/heads/main.tar.gz")
sha256sums=('SKIP')

package() {
  local srcdir_repo="$srcdir/pacmangr-main"

  install -Dm755 "$srcdir_repo/pacmangr" \
    "$pkgdir/usr/bin/pacmangr"

  install -Dm755 "$srcdir_repo/pacmangr-gui" \
    "$pkgdir/usr/bin/pacmangr-gui"

  install -Dm644 "$srcdir_repo/io.github.hei.pacmangr.desktop" \
    "$pkgdir/usr/share/applications/io.github.hei.pacmangr.desktop"

  install -Dm644 "$srcdir_repo/assets/io.github.hei.pacmangr.png" \
    "$pkgdir/usr/share/icons/hicolor/512x512/apps/io.github.hei.pacmangr.png"

  install -Dm644 "$srcdir_repo/assets/pacmangr-exit.png" \
    "$pkgdir/usr/share/pacmangr/assets/pacmangr-exit.png"

  install -Dm644 "$srcdir_repo/LICENSE" \
    "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
