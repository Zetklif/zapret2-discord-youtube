@echo off
chcp 65001 > nul
:: 65001 - UTF-8

cd /d "%~dp0"
call service.bat status_zapret
call service.bat check_updates
call service.bat load_game_filter
call service.bat load_user_lists
echo:

set "BIN=%~dp0bin\"
set "LUA=%~dp0lua\"
set "LISTS=%~dp0lists\"
cd /d %BIN%

start "zapret2: %~n0" /min "%BIN%winws2.exe" --wf-tcp-out=80,443,2053,2083,2087,2096,8443,%GameFilterTCP% --wf-udp-out=443,19294-19344,50000-50100,%GameFilterUDP% ^
--lua-init=@"%LUA%zapret-lib.lua" --lua-init=@"%LUA%zapret-antidpi.lua" ^
--blob=ACTIVE_DISCORD_UDP:@"%BIN%ACTIVE_DISCORD_UDP.bin" ^
--blob=ACTIVE_GAME_UDP:@"%BIN%ACTIVE_GAME_UDP.bin" ^
--blob=quic_initial_www_google_com:@"%BIN%quic_initial_www_google_com.bin" ^
--blob=tls_clienthello_max_ru:@"%BIN%tls_clienthello_max_ru.bin" ^
--blob=tls_clienthello_www_google_com:@"%BIN%tls_clienthello_www_google_com.bin" ^
--filter-udp=443 --hostlist="%LISTS%list-general.txt" --hostlist="%LISTS%list-general-user.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --hostlist-exclude="%LISTS%list-exclude-user.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude-user.txt"  ^
  --payload=quic_initial --lua-desync=fake:blob=quic_initial_www_google_com:repeats=11 --new ^
--filter-udp=19294-19344,50000-50100 --filter-l7=discord,stun  ^
  --payload=discord_ip_discovery,stun --lua-desync=fake:blob=ACTIVE_DISCORD_UDP:repeats=6 --new ^
--filter-tcp=2053,2083,2087,2096,8443 --hostlist-domains=discord.media --out-range=-d10 ^
  --payload=tls_client_hello --lua-desync=fake:blob=fake_default_tls:repeats=8:tcp_seq=10000000:tcp_ack=-66000:tcp_ts_up:tls_mod=rnd,dupsid,sni=www.google.com --lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=tls_clienthello_www_google_com ^
  --payload=http_req --lua-desync=fake:blob=fake_default_http:repeats=8:tcp_seq=10000000:tcp_ack=-66000:tcp_ts_up --lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=tls_clienthello_www_google_com --new ^
--filter-tcp=443 --hostlist="%LISTS%list-google.txt" --out-range=-d10 ^
  --payload=tls_client_hello --lua-desync=fake:blob=fake_default_tls:repeats=8:tcp_seq=10000000:tcp_ack=-66000:tcp_ts_up:ip_id=zero:tls_mod=rnd,dupsid,sni=www.google.com --lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=tls_clienthello_www_google_com:ip_id=zero ^
  --payload=http_req --lua-desync=fake:blob=fake_default_http:repeats=8:tcp_seq=10000000:tcp_ack=-66000:tcp_ts_up:ip_id=zero --lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=tls_clienthello_www_google_com:ip_id=zero --new ^
--filter-tcp=80,443 --hostlist="%LISTS%list-general.txt" --hostlist="%LISTS%list-general-user.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --hostlist-exclude="%LISTS%list-exclude-user.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude-user.txt" --out-range=-d10 ^
  --payload=tls_client_hello --lua-desync=fake:blob=fake_default_tls:repeats=8:tcp_seq=10000000:tcp_ack=-66000:tcp_ts_up:tls_mod=rnd,dupsid,sni=www.google.com --lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=tls_clienthello_www_google_com ^
  --payload=http_req --lua-desync=fake:blob=tls_clienthello_max_ru:repeats=8:tcp_seq=10000000:tcp_ack=-66000:tcp_ts_up --lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=tls_clienthello_www_google_com --new ^
--filter-udp=443 --ipset="%LISTS%ipset-all.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --hostlist-exclude="%LISTS%list-exclude-user.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude-user.txt"  ^
  --payload=quic_initial --lua-desync=fake:blob=quic_initial_www_google_com:repeats=11 --new ^
--filter-tcp=80,443,8443 --ipset="%LISTS%ipset-all.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --hostlist-exclude="%LISTS%list-exclude-user.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude-user.txt" --out-range=-d10 ^
  --payload=tls_client_hello --lua-desync=fake:blob=fake_default_tls:repeats=8:tcp_seq=10000000:tcp_ack=-66000:tcp_ts_up:tls_mod=rnd,dupsid,sni=www.google.com --lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=tls_clienthello_www_google_com ^
  --payload=http_req --lua-desync=fake:blob=tls_clienthello_max_ru:repeats=8:tcp_seq=10000000:tcp_ack=-66000:tcp_ts_up --lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=tls_clienthello_www_google_com --new ^
--filter-tcp=%GameFilterTCP% --ipset="%LISTS%ipset-all.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude-user.txt" --out-range=-n2 ^
  --payload=tls_client_hello --lua-desync=fake:blob=fake_default_tls:repeats=8:tcp_seq=10000000:tcp_ack=-66000:tcp_ts_up:tls_mod=rnd,dupsid,sni=www.google.com:payload=known,unknown --lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=tls_clienthello_www_google_com:payload=known,unknown ^
  --payload=http_req,unknown --lua-desync=fake:blob=tls_clienthello_max_ru:repeats=8:tcp_seq=10000000:tcp_ack=-66000:tcp_ts_up:payload=known,unknown --lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=tls_clienthello_www_google_com:payload=known,unknown --new ^
--filter-udp=%GameFilterUDP% --ipset="%LISTS%ipset-all.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude-user.txt" --out-range=-n1 ^
  --payload=unknown --lua-desync=fake:blob=ACTIVE_GAME_UDP:repeats=10:payload=known,unknown
