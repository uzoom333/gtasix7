# GTASix7

Baixa vídeos com yt-dlp e gera cortes verticais com a identidade GTASix7.
Aceita acordos com os criadores, inclusive verbais; não exige planilha ou comprovante.
Postagem manual.

## Instalar

Linux (Fedora/Debian/Ubuntu) ou macOS, com Bash e Python 3.10+:

```bash
./instalar.sh
export PATH="$HOME/.local/bin:$PATH"
```

O instalador usa sudo no Linux e baixa o yt-dlp oficial. FFmpeg precisa dos
filtros drawtext e concat, encoder AAC e libx264 ou libopenh264. O instalador
foi executado anteriormente no Fedora; os caminhos apt/Homebrew não foram
validados nesta máquina. Windows: usar WSL.

## Um link

```bash
./baixar.sh 'https://www.instagram.com/reel/ID/' --criador @parceiro \
  --legenda 'olha esse final' --gancho 'olha isso / no GTA 6' --corte 3-25
```

Só o link e `--criador` são obrigatórios. Se precisar da sua sessão do navegador:

```bash
./baixar.sh 'https://www.instagram.com/reel/ID/' --criador @parceiro \
  --cookies-do-navegador firefox
```

O yt-dlp lê a sessão local; não salve cookies no repositório. Links privados,
removidos ou indisponíveis para a sua conta podem falhar. Este projeto não é
uma extensão do navegador: usa o programa yt-dlp instalado na máquina.

## Uma fila

```bash
cp fila.exemplo.txt fila.txt  # só na primeira vez; o instalador já cria a fila
```

Preencha `fila.txt`, um vídeo por linha:

```text
@parceiro | https://www.instagram.com/reel/ID/ | legenda | gancho / segunda linha | 3-25
```

```bash
./baixar.sh
./baixar.sh --cookies-do-navegador firefox
./baixar.sh --fila outra-fila.txt
```

Falhas não interrompem os demais itens. Se algum falhar, o comando termina com
código 1. Ao executar novamente, tenta os que falharam e pula URLs concluídas.
URLs só entram em `processados.txt` depois de baixar e editar com sucesso.
Para reeditar uma URL concluída, use o arquivo local ou remova a linha do histórico.

## Arquivo local

```bash
./gtasix7.sh '/caminho/video.mp4' @parceiro 'legenda' 'gancho / linha 2' '3-25'
```

O corte precisa estar dentro da duração do vídeo, com fim maior que início.
Decimais usam ponto: `0.5-8.2`. Gancho e legenda são opcionais. Textos muito
longos podem ultrapassar a tela: use um gancho curto, dividido com ` / `.

## Resultado

- MP4 H.264, 1080×1920, 30 fps, áudio AAC estéreo a 48 kHz.
- Fundo desfocado, marca GTASix7, crédito `via @criador` e gancho nos primeiros 3 s.
- Cartão final de 2 s, gerado junto ao vídeo para manter áudio e imagem alinhados.
- Vídeos sem áudio recebem silêncio.
- Vídeo e legenda `.txt` em `prontos/`; fontes em `recebidos/`.
- Nome inclui uma chave das opções: cortes/legendas diferentes geram arquivos diferentes.
- Erros de download em `logs/`; erros de edição aparecem no terminal.

Sem publicação automática. Vídeos, fila pessoal, sessões, histórico, logs e
comprovantes ficam fora do Git. `pedido-autorizacao.md` é um modelo opcional.

## Testar

```bash
python3 -m unittest -v test_gtasix7
```

Os testes geram vídeos sintéticos, renderizam com/sem áudio, verificam corte,
resolução, duração e sincronização, decodificam os resultados e fazem um download
real com yt-dlp por HTTP local. Também cobrem falhas, retomada, duplicatas e trava
de concorrência. Tudo fica em diretórios temporários. Reels reais dependem de
link disponível e, às vezes, login; o teste local não valida o acesso ao Instagram.
