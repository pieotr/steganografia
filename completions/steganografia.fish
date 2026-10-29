# Uzupełnienia dla zainstalowanej komendy steganografia.
complete -c steganografia -f
complete -c steganografia -n __fish_use_subcommand -a embed -d 'Ukryj tekst w PNG'
complete -c steganografia -n __fish_use_subcommand -a extract -d 'Odczytaj tekst z PNG'
complete -c steganografia -n __fish_use_subcommand -a capacity -d 'Pokaż pojemność PNG'
complete -c steganografia -n __fish_use_subcommand -a jpeg -d 'Konwertuj PNG do JPEG przez DCT'
complete -c steganografia -s h -l help -d 'Pokaż pomoc'
complete -c steganografia -n '__fish_seen_subcommand_from embed' -l text -r -d 'Wiadomość UTF-8'
complete -c steganografia -n '__fish_seen_subcommand_from embed' -l text-file -r -a '(__fish_complete_suffix .txt)' -d 'Wczytaj tekst UTF-8 z pliku'
complete -c steganografia -n '__fish_seen_subcommand_from extract' -s o -l output -r -a '(__fish_complete_suffix .txt)' -d 'Zapisz tekst UTF-8 do pliku'
complete -c steganografia -n '__fish_seen_subcommand_from embed extract' -l overwrite -d 'Zezwól na nadpisanie pliku'
complete -c steganografia -n '__fish_seen_subcommand_from embed extract capacity jpeg' -a '(__fish_complete_suffix .png)' -d 'Plik obrazu'
complete -c steganografia -n '__fish_seen_subcommand_from jpeg' -l overwrite -d 'Zezwól na nadpisanie pliku'
