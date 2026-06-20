# Maintainer: HeiDumb <rockygehlot31@gmail.com>
pkgname=pacmangr
pkgver=0.1.0
pkgrel=1
pkgdesc="Animated terminal package manager for mixed Linux systems"
arch=('any')
url="https://github.com/HeiDumb/pacmangr"
license=('MIT')
depends=('python')
optdepends=(
  'pacman: Arch repository package support'
  'yay: AUR package support'
  'paru: alternate AUR package support'
  'pacseek: interactive Arch package lookup'
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
  '6d84e61a5e1828541fd9228f5e4df7ca158248187bc87381a629e7697f36a057'
  '1ca94f060630018611d08b440c3e9c2b5e58fd75d967845f60fb327e0a75ef9c'
)

package() {
  install -Dm755 pacmangr "$pkgdir/usr/bin/pacmangr"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
