import os
import sys
import json
import threading
import concurrent.futures
from collections import defaultdict
from types import SimpleNamespace

# sudo find / \( -path /mnt -o -path /proc -o -path /sys -o -path /dev \) -prune -o -type d -iname 'docker' |grep docker
# sudo du -sbh /var/lib/docker

os.system("")

LOG_FILE = "scan_results.log"
class Colors:
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    RESET = "\033[0m"  # Сброс цвета


def log_message(message, console_print=True):
    """Универсальная функция для логирования"""
    if console_print:
        print(message)
    else:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(message + "\n")


class MyProgress:
    def __init__(self):
        self.progress_symbols = ['\\', '|', '/', '-']
        self.p1 = 0
        self.p1_name = ""
        self.p2 = 0
        self.p2_name = ""
        self.lock = threading.Lock()

    def out(self):
        with self.lock:
            sys.stdout.write("\033[3F")
            sys.stdout.write(f"\nПрогресс 1: {self.progress_symbols[self.p1 % len(self.progress_symbols)]} Thread: {self.p1_name}\nПрогресс 2: {self.progress_symbols[self.p2 % len(self.progress_symbols)]} Thread: {self.p2_name}\n")
            sys.stdout.flush()

class FastThreadSafeCache:
    def __init__(self):
        self._data = defaultdict(int)
        self._lock = threading.Lock()  # Для операций записи
        self._read_lock = threading.RLock()  # Для чтения (если нужно атомарное)

    def __contains__(self, key):
        """Потокобезопасная проверка наличия ключа"""
        with self._read_lock:
            return key in self._data

    def update(self, key, value):
        """Обновление с блокировкой записи"""
        with self._lock:
            self._data[key] = value

    def get(self, key, default=None):
        """Потокобезопасное получение значения"""
        with self._read_lock:
            return self._data.get(key, default)

    def snapshot(self):
        """Атомарная копия данных"""
        with self._lock:
            return dict(self._data)


def find_directories(path, max_depth=1, size_filter=None, name_filter=None, exclude_dirs=None):
    """
    Поиск директорий с заданными параметрами.
    
    Аргументы:
    path -- root dir to start from
    max_depth -- max deep to search
    size_filter -- фильтр по размеру (например, '>2G')
    name_filter -- фильтр по имени директории
    exclude_dirs -- список директорий для исключения
    
    Возвращает список кортежей (размер, путь)
    """
    
    if exclude_dirs is None:
        exclude_dirs = ["/proc", "/mnt", "/sys", "/dev", "/run", "/tmp", "/var/tmp"]
    
    results = []
    progress = MyProgress()
    size_cache = FastThreadSafeCache() # Cache for storing directory sizes
    
    log_message(f"Поиск в: {path}, макс. глубина: {max_depth}")
    log_message(f"Фильтры: размер = '{size_filter or ''}', имя = '{name_filter or ''}'")
    log_message(f"Исключения: {exclude_dirs}\n")
    
    
    def is_excluded(current_path):
        """Проверяет, нужно ли исключить директорию"""
        return any(current_path.startswith(exclude_dir) for exclude_dir in exclude_dirs)

    def get_file_size(file_path):
        """Получает размер файла"""
        progress.p2_name = threading.current_thread().name
        progress.out()
        progress.p2 += 1

        try:
            if os.path.islink(file_path) or not os.path.exists(file_path):
                return 0
            return os.path.getsize(file_path)
        except (OSError, PermissionError) as e:
            log_message(f"Нет прав доступа к файлу: {file_path}: {e}")
            return 0
        except Exception as e:
            log_message(f"Ошибка при обработке файла {file_path}: {e}")
            return 0

    def calculate_size(current_path):
        """Calculate the Size of directory in multithreading"""
        progress.p2_name = f"calculate_size for {pad_with_spaces(truncate_middle(current_path), 50)}"
        progress.out()
        progress.p2 += 1

        size = size_cache.get(current_path)
        if size:
            return size

        total_size = 0
        try:
            with os.scandir(current_path) as entries:
                for entry in entries:
                    if entry.is_file():
                        total_size += entry.stat().st_size
                    elif entry.is_symlink():
                        # log_message(f"\t\tCZ is symlink:{entry.path} {entry.is_symlink()}", False)
                        continue
                    elif entry.is_dir():
                        # log_message(f"\t\tCZ :{entry.path} is excluded: {is_excluded(entry.path)}", False)
                        total_size += calculate_size(entry.path)
            """         with concurrent.futures.ThreadPoolExecutor(14, "calc_size") as executor:
                            file_futures = []
                            for dirpath, dirnames, filenames in os.walk(current_path):
                                if is_excluded(dirpath):
                                    dirnames[:] = []
                                    continue
                                file_futures.extend(
                                    executor.submit(get_file_size, os.path.join(dirpath, f))
                                    for f in filenames
                                )
                            
                            for future in concurrent.futures.as_completed(file_futures):
                                total_size += future.result()
            """

        except Exception as e:
            log_message(f"Error under calculating size {current_path}: {e}")
        
        size_cache.update(current_path, total_size)
        return total_size


    def build_directory_tree(results):
        """Build the tree of directories from the Result"""
        tree = defaultdict(dict)
        for item in sorted(results, key=lambda x: x["path"]):
            parts = item["path"].split(os.sep)
            current = tree
            has_leaf = len(parts) > 2
            for part in parts[1:]:  # Пропускаем пустой первый элемент для абсолютных путей
                if part not in current:
                    current[part] = defaultdict(dict)
                current = current[part]
                current["__leaf__"] = has_leaf and part == parts[-1]
            
            current["__size__"] = item["size"]
            current["__raw_size__"] = item["raw_size"]
        return tree

    def traverse_directories(start_path):
        """Base function for traverse directories"""
        # pool with X workers
        with concurrent.futures.ThreadPoolExecutor(7, "traverse") as executor:
            futures = {}
            results = []
            
            def is_root(path):
                """Проверяет, является ли путь корневым."""
                path = os.path.abspath(path).rstrip(os.sep)
                return not os.path.dirname(path)  # Пустой dirname → корень

            def get_dir_entry(path):
                """Возвращает объект, похожий на DirEntry, даже для корня."""
                path = os.path.abspath(path)
                
                # Если это корень (например, '/' или 'C:\')
                # log_message(f"\t\tGDE {path} dirname():{os.path.dirname(path)} w/sep:{os.path.dirname(path + os.sep):}")
                if is_root(path):
                    return SimpleNamespace(
                        name=os.path.basename(path.rstrip(os.sep)) or path,
                        path=path,
                        is_dir=lambda *_: True,
                        is_file=lambda *_: False,
                        stat=lambda *_: os.stat(path),
                    )
                
                # Обычный файл/директория (через scandir)
                dirname, basename = os.path.split(path)
                try:
                    with os.scandir(dirname) as it:
                        return next((entry for entry in it if entry.name == basename), None)
                except (PermissionError, FileNotFoundError):
                    return None

            def schedule(entry, depth):
                """add to the pool"""
                if depth > max_depth:
                    return
                future = executor.submit(process_directory, entry, depth)
                futures[future] = (entry, depth)
            
            def scanDir(path, depth):
                try:
                    with os.scandir(path) as entries:
                        for entry in entries:
                            # log_message(f"\t\tscanDir: {entry.path} is Sym: {entry.is_symlink()}", False)

                            if entry.is_dir() and not entry.is_symlink():
                                schedule(entry, depth)
                except Exception as e:
                    log_message(f"Ошибка при сканировании {path}: {e}")

            # Перебор директорий и расчет размеров
            def process_directory(entry, current_depth):
                log_message(f"\tDir start: {entry.path} >", False)
                
                # Обновление прогресса
                progress.p1_name = f"{threading.current_thread().name} > {pad_with_spaces(truncate_middle(entry.path), 50)}"
                progress.out()
                progress.p1 += 1
                
                if is_excluded(entry.path):
                    # log_message(f"\t\t[{entry.path}] - excluded by exclusions", False)
                    return None
                
                # FILTER 1 (by name)
                if is_root(entry.path):# or not filterByName(os.path.basename(entry.path)):
                    # log_message(f"\t\t[{entry.path}] - excluded by /", False)
                    scanDir(entry.path, current_depth + 1)
                    return None
                if not filterByName(os.path.basename(entry.path)):
                    scanDir(entry.path, current_depth + 1)

                # Рассчет размера
                if entry.is_file():
                    total_size = entry.stat().st_size
                else:
                    total_size = calculate_size(entry.path)
                log_message(f"\t\tdir size: {entry.path} = {total_size}", False)

                # FILTER 2 (by size)
                if size_filter:
                    if not filterBySize(total_size):
                        return None
                    if name_filter and not filterByName(os.path.basename(entry.path)):
                        return None

                return {"path": entry.path, "size": formatSize(total_size), "raw_size": total_size}


            schedule(get_dir_entry(start_path), 0)
            
            while futures:
                done, _ = concurrent.futures.wait(
                    futures.keys(), 
                    return_when = concurrent.futures.FIRST_COMPLETED,
                    timeout = None
                )
                
                for future in done:
                    path, depth = futures.pop(future)
                    result = future.result()
                    if result:
                        # log_message(f"\t\t{result["path"]} - {result["size"]}", False)
                        results.append(result)
                        # Планируем обработку поддиректорий
                        # scanDir(path, depth + 1)
            
            return results


    log_message("Searching...\n\n")
    results = traverse_directories(path)
    log_message(f"\nSearching done. Found directories: {len(results)}")
    
    # Строим дерево и возвращаем оба результата
    directory_tree = build_directory_tree(results)
    return {
        "flat_list": results,
        "directory_tree": directory_tree
    }


#region TOOLS
def convertSize(size_str):
    """Конвертация размера в байты"""
    if not size_str:
        return 0
    units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    if size_str[-1].upper() in units:
        return int(float(size_str[:-1]) * units[size_str[-1].upper()])
    return int(size_str)

def filterBySize(size):
    operator = size_filter[0]
    threshold = convertSize(size_filter[1:])
    return {
        '>': lambda: size > threshold,
        '<': lambda: size < threshold,
        '>=': lambda: size >= threshold,
        '<=': lambda: size <= threshold,
        '==': lambda: size == threshold
    }.get(operator, lambda: True)()

def formatSize(size):
    # Форматирование размера
    size_units = ['B', 'K', 'M', 'G', 'T']
    size_value = size
    for unit in size_units[:-1]:
        if size_value < 1024:
            break
        size_value /= 1024
    return f"{size_value:.1f}{size_units[size_units.index(unit)]}"

def filterByName(current_path):
    """filter current path by name_filter"""
    return name_filter and name_filter in current_path

def truncate_middle(text, max_length=50, keep=23):
    """truncate a string by length (remove a middle symbols in a line)"""
    if not isinstance(text, str):
        return str(text)
    
    text = text.strip()
    if len(text) <= max_length:
        return text
        
    # keep = max(1, min(keep, len(text)//2))  # Гарантируем хотя бы 1 символ с каждой стороны
    return f"{text[:keep]}...{text[-keep:]}"

def pad_with_spaces(text, target_length, align='left'):
    """
    Дополняет строку пробелами до заданной длины.
    
    Параметры:
        text (str): исходная строка
        target_length (int): желаемая длина строки
        align (str): выравнивание ('left', 'right', 'center')
    
    Возвращает:
        str: строка, дополненная пробелами
    """
    if len(text) >= target_length:
        return text
    
    spaces_needed = target_length - len(text)
    
    if align == 'left':
        return text + ' ' * spaces_needed
    elif align == 'right':
        return ' ' * spaces_needed + text
    elif align == 'center':
        left_spaces = spaces_needed // 2
        right_spaces = spaces_needed - left_spaces
        return ' ' * left_spaces + text + ' ' * right_spaces
    else:
        raise ValueError("Недопустимое значение align. Допустимо: 'left', 'right', 'center'")

def print_directory_tree(tree, prefix=""):
    """Рекурсивно печатает дерево директорий"""
    if not tree:
        return
    
    log_message(f"\t\t\tTree.items: {tree.items()} {len(tree.items())}", False)
    items = sorted(
        [(k, v) for k, v in tree.items() if not k.startswith("__")],
        key=lambda x: x[1].get("__raw_size__", 0),
        reverse=True
    )
    
    for i, (name, subtree) in enumerate(items):
        is_last = i == len(items) - 1
        size = subtree.get("__size__", "")
        if size:
            size = f"({size})"
        # log_message(f"Node: {name} {size}", False)
        
        if filterByName(name):
            name = f"{Colors.RED}{name}{Colors.RESET}"
        if subtree.get("__leaf__") and size_filter and filterBySize(subtree.get("__raw_size__", 0)):
            size = f"{Colors.MAGENTA}{size}{Colors.RESET}"

        if prefix == "":
            log_message(f"/{name} {size}")
        else:
            log_message(f"{prefix}{'└── ' if is_last else '├── '}{name} {size}")
        
        new_prefix = prefix + ("    " if is_last else "│   ")
        print_directory_tree(subtree, new_prefix)
#endregion TOOLS


if __name__ == "__main__":
    try:
        # Очистка лог-файла перед запуском
        with open(LOG_FILE, "w") as f:
            f.write("=== Начало сканирования ===\n")

        if len(sys.argv) < 2:
            log_message("Usage: python find.py <start_path> [max_deep] [size_filter] [name_filter]")
            sys.exit(1)
        path = sys.argv[1]
        max_depth = int(sys.argv[2]) if len(sys.argv) > 2 else None
        size_filter = sys.argv[3] if len(sys.argv) > 3 else None
        name_filter = sys.argv[4] if len(sys.argv) > 4 else None
        
        result = find_directories(path, max_depth, size_filter, name_filter)
        
        log_message("\nResult as JSON:", False)
        log_message(json.dumps(result["flat_list"], indent=2, ensure_ascii=False), False)
        log_message("\nTree of dirs:")
        print_directory_tree(result["directory_tree"])
        
        # Дополнительная информация в лог
        with open(LOG_FILE, "a") as f:
            f.write("\n=== Сканирование завершено ===\n")
            f.write(f"Всего обработано: {len(result['flat_list'])} директорий\n")
        
    except Exception as e:
        with open(LOG_FILE, "a") as f:
            f.write(f"\n!!! ОШИБКА: {str(e)}\n")
