# pacmangr GitHub Plugin System

The GitHub plugin system allows you to add custom GitHub repositories as package sources in pacmangr.

## Configuration

Create or edit the file `~/.config/pacmangr/plugins.json` to add GitHub repositories:

```json
{
  "plugins": {
    "user/repo-name": "https://github.com/user/repo-name.git",
    "dim-ghub/caelestia-shell-git": "https://github.com/dim-ghub/caelestia-shell-git.git",
    "dim-ghub/caelestia-cli-git": "https://github.com/dim-ghub/caelestia-cli-git.git"
  }
}
```

## Usage

### Searching for Plugins

Press `/` to search and enter a query. GitHub plugins will be included in the search results with the "gh" tag.

### Installing Plugins

1. Search for a GitHub plugin by name
2. Navigate to the plugin in the results
3. Press `Space` to mark it
4. Press `Enter` to install
5. The plugin will be cloned to `~/.local/share/pacmangr/plugins/{user}/{repo}`

### Viewing Installed Plugins

Press `i` to view installed packages. GitHub plugins will appear with the "gh" tag and can be identified by the repository path.

### Removing Plugins

1. Press `i` to view installed packages
2. Navigate to the GitHub plugin
3. Press `Space` to mark it
4. Press `Enter` to remove
5. The plugin directory will be deleted

## Plugin Installation Location

GitHub plugins are cloned to:
```
~/.local/share/pacmangr/plugins/{user}/{repo}
```

For example, the `dim-ghub/caelestia-cli-git` plugin will be installed at:
```
~/.local/share/pacmangr/plugins/dim-ghub/caelestia-cli-git
```

## Updates

To update an existing GitHub plugin:
1. Search for the plugin
2. If it's already installed, mark it
3. Press `Enter` to reinstall/update

This will perform a `git pull --rebase` to update the repository to the latest version.

## Configuration File Examples

### Single Plugin
```json
{
  "plugins": {
    "username/repository": "https://github.com/username/repository.git"
  }
}
```

### Multiple Plugins
```json
{
  "plugins": {
    "user1/repo1": "https://github.com/user1/repo1.git",
    "user2/repo2": "https://github.com/user2/repo2.git",
    "user3/repo3": "https://github.com/user3/repo3.git"
  }
}
```

### With SSH URLs (if SSH is configured)
```json
{
  "plugins": {
    "username/repository": "git@github.com:username/repository.git"
  }
}
```

## Troubleshooting

- **Plugin not found in search**: Make sure the plugin is defined in `~/.config/pacmangr/plugins.json`
- **Clone failed**: Verify the repository URL is correct and accessible
- **Permission denied**: Make sure `~/.local/share/pacmangr/plugins/` directory exists and is writable
- **git not found**: Ensure `git` is installed on your system (`pacman -S git` on Arch)
