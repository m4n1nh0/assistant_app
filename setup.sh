#!/bin/bash

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}"
echo "  ╔══════════════════════════════════╗"
echo "  ║      Assistente — Setup     ║"
echo "  ╚══════════════════════════════════╝"
echo -e "${NC}"

if ! command -v flutter &> /dev/null; then
    echo -e "${YELLOW}Flutter não encontrado. Instalando via snap...${NC}"
    if command -v snap &> /dev/null; then
        sudo snap install flutter --classic
    else
        echo "Instale o Flutter manualmente: https://flutter.dev/docs/get-started/install"
        exit 1
    fi
fi

echo -e "${GREEN}✓ Flutter encontrado: $(flutter --version | head -1)${NC}"

flutter config --enable-linux-desktop 2>/dev/null || true
flutter config --enable-macos-desktop 2>/dev/null || true
flutter config --enable-windows-desktop 2>/dev/null || true

echo -e "${BLUE}Instalando dependências...${NC}"
flutter pub get

echo -e "${GREEN}✓ Dependências instaladas${NC}"

OS="$(uname -s)"
case "${OS}" in
    Linux*)
        echo -e "${BLUE}Executando no Linux...${NC}"
        flutter run -d linux
        ;;
    Darwin*)
        echo -e "${BLUE}Executando no macOS...${NC}"
        flutter run -d macos
        ;;
    CYGWIN*|MINGW*|MSYS*)
        echo -e "${BLUE}Executando no Windows...${NC}"
        flutter run -d windows
        ;;
    *)
        echo "Plataforma desconhecida: ${OS}"
        echo "Execute manualmente: flutter run -d <windows|macos|linux>"
        ;;
esac
