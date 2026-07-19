# Maintainer: HeiDumb <rockygehlot31@gmail.com>
pkgname=pacmangr
pkgver=0.2.1
pkgrel=1
pkgdesc="Terminal interface for native package managers"
arch=('any')
url="https://github.com/HeiDumb/pacmangr"
license=('MIT')
depends=('python')
optdepends=(
  'pacman: Arch repository package support'
  'yay: AUR package support'
  'paru: alternate AUR package support'
  'pacseek: interactive Arch package lookup'
  'downgrade: Arch package version history and downgrade support'
  'flatpak: Flatpak application support'
  'apt: Debian/Ubuntu package support'
  'snapd: Snap package support'
  'cargo: Rust crate support'
  'npm: Node package support'
  'python-pip: Python package support'
  'pipx: Python application support'
  'ruby: gem package support'
  'luarocks: Lua package support'
)
source=('pacmangr' 'LICENSE')
sha256sums=(
  '5f174c85ead499def67c2b8c8ee0e0d7abfa5a1210bc10ab7e4b22ec4c8742bb'
  '1ca94f060630018611d08b440c3e9c2b5e58fd75d967845f60fb327e0a75ef9c'
)

package() {
  install -Dm755 pacmangr "$pkgdir/usr/bin/pacmangr"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
