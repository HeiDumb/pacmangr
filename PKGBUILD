# Maintainer: HeiDumb <rockygehlot31@gmail.com>
pkgname=pacmangr
pkgver=0.4.2
pkgrel=1
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

source=("pacmangr-${pkgver}.tar.gz::https://github.com/HeiDumb/pacmangr/archive/refs/tags/${pkgver}.tar.gz")
sha256sums=('f676f70ba126e525e2f9f27b4c5b41267449c6edf3a5a6811199876e92834a7b')

package() {
  local srcdir_repo="$srcdir/pacmangr-$pkgver"

  install -Dm755 "$srcdir_repo/pacmangr" \
    "$pkgdir/usr/bin/pacmangr"

  install -Dm755 "$srcdir_repo/pacmangr-gui" \
    "$pkgdir/usr/bin/pacmangr-gui"

  install -d "$pkgdir/usr/bin/pacmangr_core"
  install -m644 "$srcdir_repo"/pacmangr_core/*.py \
    "$pkgdir/usr/bin/pacmangr_core/"

  install -d "$pkgdir/usr/bin/pacmangr_gui"
  install -m644 "$srcdir_repo"/pacmangr_gui/*.py \
    "$pkgdir/usr/bin/pacmangr_gui/"

  install -Dm644 "$srcdir_repo/io.github.hei.pacmangr.desktop" \
    "$pkgdir/usr/share/applications/io.github.hei.pacmangr.desktop"

  install -Dm644 "$srcdir_repo/assets/io.github.hei.pacmangr.png" \
    "$pkgdir/usr/share/icons/hicolor/512x512/apps/io.github.hei.pacmangr.png"

  install -Dm644 "$srcdir_repo/assets/pacmangr-exit.png" \
    "$pkgdir/usr/share/pacmangr/assets/pacmangr-exit.png"

  install -Dm644 "$srcdir_repo/LICENSE" \
    "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
