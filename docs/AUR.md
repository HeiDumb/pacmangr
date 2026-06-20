# AUR Publishing Notes

The root `PKGBUILD` is designed for a simple AUR package named `pacmangr`.

## Local Test

```sh
makepkg -f
sudo pacman -U pacmangr-*.pkg.tar.zst
```

## Update Checksums

Whenever `pacmangr` changes:

```sh
sha256sum pacmangr
makepkg --printsrcinfo > .SRCINFO
```

Commit both `PKGBUILD` and `.SRCINFO`.

## Submit To AUR

```sh
git clone ssh://aur@aur.archlinux.org/pacmangr.git aur-pacmangr
cp PKGBUILD .SRCINFO pacmangr LICENSE aur-pacmangr/
cd aur-pacmangr
makepkg -f
git add PKGBUILD .SRCINFO pacmangr LICENSE
git commit -m "Initial import"
git push
```

The package includes the single Python script directly. A future release can
switch to GitHub tag tarballs once the repository has stable tags.
