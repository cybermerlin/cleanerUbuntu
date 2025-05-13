#!/bin/bash

# Function to display disk usage
# $dir - start directory count
# $max_depth - Использование: $0 <директория> <максимальный_уровень_вложенности>
# $size_filter - Пример фильтра: '>2G' для размера больше 2 Гб, '<100M' для размера меньше 100 Мб
# $name_filter - Пример фильтра имени: 'documents' для директорий, содержащих 'documents' в имени
display_disk_usage() {
    echo -e "\nAnalyze disk usage:"
    df -h /

    local dir="$1"
    local max_depth="$2"
    local size_filter="$3"
    local name_filter="$4"
    
    # Проверка аргументов
    if [ -z "$dir" ] || [ -z "$max_depth" ]; then
        echo "Использование: $0 <директория> <максимальный_уровень_вложенности>"
        echo "Пример фильтра: '>2G' для размера больше 2 Гб, '<100M' для размера меньше 100 Мб"
        echo "Пример фильтра имени: 'documents' для директорий, содержащих 'documents' в имени"
        return 1
    fi
    if [ ! -d "$dir" ]; then
        echo "Ошибка: Директория $dir не существует"
        return 1
    fi

    time python3 find.py "$dir" "$max_depth" "$size_filter" "$name_filter" | while read -r line; do
        echo "$line"
    done
}


main() {
    # Проверка прав суперпользователя
    if [ "$EUID" -ne 0 ]; then
        echo "Пожалуйста, запустите этот скрипт с правами суперпользователя:"
        echo "sudo $0 $*"
        exit 1
    fi

    echo "Remove apt and another old and garbage, temporary, logs"
    askExit
    df -h /
    
    apt autoremove -y --purge
    apt clean -y
    apt autoclean -y


    # Removes old revisions of snaps
    # CLOSE ALL SNAPS BEFORE RUNNING THIS
    set -eu
    snap list --all | awk '/disabled/{print $1, $3}' | \
        while read snapname revision; do
            snap remove "$snapname" --revision="$revision"
        done

    echo "Removing old kernels..."
    current_kernel=$(uname -r | sed "s/-generic//")
    dpkg -l 'linux-*' | sed "/^ii/!d;/"$current_kernel"/d;s/^[^ ]* [^ ]* \([^ ]*\).*/\1/;/[0-9]/!d" | xargs apt-get -y purge

    # Clear temporary files
    echo "Clearing temporary files..."
    rm -rf /tmp/*
    rm -rf /var/tmp/*
    rm -rf /etc/apk/cache/* /var/cache/* /var/lib/apt/lists/* /var/log/* /usr/share/doc/* /usr/share/man/*

    # Empty trash
    echo "Emptying trash..."
    rm -rf ~/.local/share/Trash/*

    # Remove thumbnail cache
    echo "Removing thumbnail cache..."
    rm -rf ~/.cache/thumbnails/*

    LC_ALL=C dpkg -l | awk '/^rc/ {print $2}' | xargs sudo dpkg --purge --pending

    #Removes old revisions of snaps
    #CLOSE ALL SNAPS BEFORE RUNNING THIS
    set -eu
    LANG=en_US.UTF-8
    snap list --all | awk '/disabled/{print $1, $3}' | while read snapname revision; do
        echo "$snapname" "$revision"
        snap remove "$snapname" --revision="$revision"
    done


    echo "journal systemd"
    journalctl --disk-usage
    journalctl --vacuum-time=7d

    df -h /
}


# Функция для выполнения очистки файлов не входящих в пакеты Пакетного менеджера
cruftCln() {
    # Проверка прав суперпользователя
    if [ "$EUID" -ne 0 ]; then
        echo "Пожалуйста, запустите этот скрипт с правами суперпользователя:"
        echo "sudo $0 $*"
        exit 1
    fi
    echo "Поиск ненужных файлов..."
    askExit
    
    # Получаем список ненужных файлов
    cruft_files=$(sed -n '/---- missing: dpkg ----/,/---- unexplained: \/ ----/{
  /---- missing: dpkg ----/d
  /---- unexplained: \/ ----/d
  p
}' cruft.log | grep -v '^end\.$')
    echo "$cruft_files" > cruft-mis-dpkg.log
    
    # Подсчет общего освобождаемого пространства
    total_space=0
    echo "$cruft_files" | while read -r file; do
        if [ -e "$file" ]; then
            file_size=$(du -sb "$file" 2>/dev/null | cut -f1)
            if [ -n "$file_size" ]; then
                total_space=$(($total_space + $file_size))
            fi
        fi
    done
    
    # Конвертация размера в удобочитаемый формат
    if [ $total_space -lt 1024 ]; then
        echo "Общее освобождаемое пространство: $total_space байт"
    elif [ $total_space -lt 1048576 ]; then
        echo "Общее освобождаемое пространство: $(echo "scale=2; $total_space/1024" | bc) КБ"
    elif [ $total_space -lt 1073741824 ]; then
        echo "Общее освобождаемое пространство: $(echo "scale=2; $total_space/1048576" | bc) МБ"
    else
        echo "Общее освобождаемое пространство: $(echo "scale=2; $total_space/1073741824" | bc) ГБ"
    fi
    
    # Подтверждение очистки
    echo "Вы уверены, что хотите выполнить очистку? (y/n)"
    read -r confirm
    
    if [ "$confirm" = "y" ]; then
        echo "$cruft_files" | while read -r file; do
            if [ -e "$file" ]; then
                if rm -rf "$file"; then
                    echo "Удален: $file"
                else
                    echo "Ошибка при удалении: $file"
                fi
            else
                echo "Пропущен (не существует): $file"
            fi
        done
        echo "Очистка завершена."
    else
        echo "Очистка отменена."
    fi
}

cruftAnal() {
    echo "Выполнение сухой проверки..."
    cruft 2>&1 | tee cruft.log
    echo "Сухая проверка завершена."
}

dockerCln() {
    echo "Clean up docker files"
    askExit

    docker system prune --all --volumes
    docker image prune --all
    docker container prune

    docker system df
    docker volume prune
    docker buildx prune --all
}

askExit() {
    echo -e "\nStop? [y/n]"
    read -r answer
    if [ "$answer" = "y" ]; then exit 0; fi
}


while true; do
    # Display menu
    echo -e "\nДобро пожаловать в скрипт очистки ненужных файлов!"
    echo "Please select a function to execute:"
    echo -e "\e[31m\t1)\e[32m calculate disk usage"
    echo -e "\e[31m\t2)\e[32m main"
    echo -e "\e[31m\t3)\e[32m docker"
    echo -e "\e[31m\t4)\e[32m cruft cleanup from 'missing: dpkg' group"
    echo -e "\e[31m\t5)\e[32m cruft analyze"
    echo -e "\e[31m\t6)\e[32m compact FS"
    echo -e "\e[31m\t7)\e[32m exit"
    echo -e "\e[0m"
    # Read user input
    read -p "Enter a number: " choice
    echo ""

    # Execute the chosen function
    case $choice in
        1) display_disk_usage  "/" "1" ">1G" ;;
        2) main ;;
        3) sudo -u "$SUDO_USER" bash -c "$(declare -f dockerCln); dockerCln" ;;
        4) cruftCln ;;
        5) cruftAnal ;;
        6) e4defrag /dev/* ;;
        7) exit 0 ;;
        *) echo "Invalid input. Please enter a number from the list above" ;;
    esac
done
