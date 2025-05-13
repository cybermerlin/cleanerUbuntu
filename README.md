# Cleaner for Ubuntu

- [find](find.py) - function to find by:
    - name
    - size
  
  and then:
  + print as Tree into the Terminal.
  + write in log as JSON.
  + Executing as multithread.
  + Shows 2 Progress bars as work progresses.
  + ![alt text](image.png)

  Arguments:
  - **path** -- root dir to start from
  - **max_depth** -- max depth to search
  - **size_filter** -- size filter (e.g., '>2G')
  - **name_filter** -- directory name filter
  - **exclude_dirs** -- list of directories to exclude
- [freeup](freeup.sh) - function to clean up Snapd storage.
  + show menu to select which case would you like to run
    
    ![alt text](image-1.png)
  + calculating disk usage (before cleanup to compare a result)
  + docker space usages cleaning
  + `cruft` tool to get unnecessary files (not included in packages)
  + compact FS (defragmentation)


## TODO

- [ ] full translate to mono language
- [ ] add selection to choose the interface language
- [ ] add a menu item: "searching (by name, size, place)"
- [ ] add run find.py before and after docker cleanup
