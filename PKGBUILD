# Maintainer: HeiDumb <rockygehlot31@gmail.com>
pkgname=pacmangr
pkgver=0.3.0
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
source=('pacmangr' 'pacmangr-gui' 'io.github.hei.pacmangr.desktop' 'io.github.hei.pacmangr.png' 'LICENSE')
sha256sums=('9d39d7b3eef3455f5f88bccd5a93f65e0b63ac861f73402c1e8deb6537c7df43'
            '0be13eec91510c2f58ac3d7677e47c29d85e4c16248667a67f2ceb083ed3ba92'
            'df2610de7d8939e42d20fed92a9ec3c99f4f154279374960b1075a0bff462fca'
            'a891e45191eae6d054fce2b4b1ba53eb55f936d60d51a492c6e37366784120cc'
            '1ca94f060630018611d08b440c3e9c2b5e58fd75d967845f60fb327e0a75ef9c')

package() {
  install -Dm755 pacmangr "$pkgdir/usr/bin/pacmangr"
  install -Dm755 pacmangr-gui "$pkgdir/usr/bin/pacmangr-gui"
  install -Dm644 io.github.hei.pacmangr.desktop "$pkgdir/usr/share/applications/io.github.hei.pacmangr.desktop"
  install -Dm644 io.github.hei.pacmangr.png "$pkgdir/usr/share/icons/hicolor/512x512/apps/io.github.hei.pacmangr.png"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
