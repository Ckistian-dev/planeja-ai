import requests
import json
import sys
import os
import qrcode
import webbrowser
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env para o ambiente
load_dotenv()

# --- CONFIGURAÇÕES CARREGADAS DO ARQUIVO .env ---
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") 
# ------------------------------------------------

def check_config():
    """Verifica se as configurações essenciais foram carregadas."""
    missing = []
    if not EVOLUTION_API_URL: missing.append("EVOLUTION_API_URL")
    if not EVOLUTION_API_KEY: missing.append("EVOLUTION_API_KEY")
    if not WEBHOOK_URL: missing.append("WEBHOOK_URL (necessário para criar instâncias)")
    
    if "EVOLUTION_API_URL" in missing or "EVOLUTION_API_KEY" in missing:
        print(f"❌ Erro Crítico de Configuração: As seguintes variáveis devem estar no arquivo .env: {', '.join(missing)}")
        return False
    return True

def _obter_e_abrir_qrcode(nome_da_instancia: str):
    """
    Função interna para buscar o QR Code, salvar como imagem e abrir o arquivo.
    """
    connect_url = f"{EVOLUTION_API_URL}/instance/connect/{nome_da_instancia}"
    headers = {"apikey": EVOLUTION_API_KEY}
    print(f"\n⏳ Buscando QR Code para a instância '{nome_da_instancia}'... (Isso pode levar até 90 segundos)")

    try:
        response = requests.get(connect_url, headers=headers, timeout=90)
        response.raise_for_status()
        data = response.json()
        qr_code_string = data.get('code') or data.get('qrcode', {}).get('code')

        if qr_code_string:
            print("✅ QR Code recebido! Salvando como 'qrcode.png' e abrindo...")
            img = qrcode.make(qr_code_string)
            file_path = os.path.join(os.getcwd(), "qrcode.png")
            img.save(file_path)
            webbrowser.open(file_path)
            print("\n" + "="*50)
            print("📷 A imagem do QR Code foi aberta.")
            print("   Escaneie com seu WhatsApp para conectar.")
            print("="*50)
        else:
            print(f"❌ Erro: A resposta da API não continha um QR Code. Verifique o status da instância.")
            print("   Resposta recebida:", data)

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Erro ao obter o QR Code: {e}")
        if e.response is not None:
            print(f"   Detalhes: {e.response.text}")

def criar_instancia():
    """
    Cria uma nova instância, configura o webhook e exibe o QR Code.
    """
    nome_da_instancia = input("Digite o nome para a nova instância: ").strip()
    if not nome_da_instancia:
        print("❌ O nome da instância não pode ser vazio.")
        return

    create_url = f"{EVOLUTION_API_URL}/instance/create"
    headers = {"Content-Type": "application/json", "apikey": EVOLUTION_API_KEY}
    
    payload = {
        "instanceName": nome_da_instancia,
        "integration": "WHATSAPP-BAILEYS",
        "qrcode": True,
        "webhook": {
            "url": WEBHOOK_URL,
            "enabled": True,
            "events": [
                "MESSAGES_UPSERT"
            ]
        },
        "settings": {
            "groupsIgnore": False,
            "alwaysOnline": False,
            "readMessages": False,
            "readStatus": False,
            "syncFullHistory": True
        }
    }

    print(f"\n⏳ Criando a instância: '{nome_da_instancia}' com o webhook '{WEBHOOK_URL}'...")
    try:
        response = requests.post(create_url, headers=headers, data=json.dumps(payload), timeout=60)
        response.raise_for_status()
        print("\n✅ Instância e Webhook configurados com sucesso!")
        print("--- RESPOSTA DA API ---")
        print(json.dumps(response.json(), indent=2))
        _obter_e_abrir_qrcode(nome_da_instancia)
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Erro ao criar a instância: {e}")
        if e.response is not None:
            print(f"   Detalhes: {e.response.text}")

def deletar_instancia():
    """
    Deleta uma instância existente após fazer logout.
    """
    nome_da_instancia = input("Digite o nome da instância que deseja deletar: ").strip()
    if not nome_da_instancia:
        print("❌ O nome da instância não pode ser vazio.")
        return

    confirmacao = input(f"❓ ATENÇÃO: Tem certeza que deseja deletar '{nome_da_instancia}'? (s/N): ").lower()
    if confirmacao != 's':
        print("Operação cancelada.")
        return

    delete_url = f"{EVOLUTION_API_URL}/instance/delete/{nome_da_instancia}"
    logout_url = f"{EVOLUTION_API_URL}/instance/logout/{nome_da_instancia}"
    headers = {"apikey": EVOLUTION_API_KEY}

    print(f"\n⏳ Fazendo LOGOUT da instância: '{nome_da_instancia}'...")
    try:
        requests.delete(logout_url, headers=headers, timeout=60)
        print("✅ Logout realizado com sucesso (ou instância já estava desconectada).")
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Aviso ao tentar fazer logout: {e}. Prosseguindo com a deleção.")

    print(f"\n⏳ Deletando a instância: '{nome_da_instancia}'...")
    try:
        response_delete = requests.delete(delete_url, headers=headers, timeout=60)
        response_delete.raise_for_status()
        print("\n" + "="*50)
        print("✅ Instância deletada com sucesso!")
        print("="*50)
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Erro ao deletar a instância: {e}")
        if e.response is not None:
            print(f"   Detalhes: {e.response.text}")

def status_instancias():
    """
    Busca e exibe o status de todas as instâncias na API.
    """
    status_url = f"{EVOLUTION_API_URL}/instance/fetch"
    headers = {"apikey": EVOLUTION_API_KEY}
    print("\n⏳ Buscando status de todas as instâncias...")

    try:
        response = requests.get(status_url, headers=headers, timeout=30)
        response.raise_for_status()
        instancias = response.json()

        if not instancias:
            print("ℹ️ Nenhuma instância encontrada.")
            return

        print("\n--- STATUS DAS INSTÂNCIAS ---")
        for instancia in instancias:
            nome = instancia.get('instance', {}).get('instanceName', 'N/A')
            status = instancia.get('instance', {}).get('status', 'N/A')
            print(f"  - Nome: {nome:<25} | Status: {status}")
        print("----------------------------\n")

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Erro ao buscar o status das instâncias: {e}")
        if e.response is not None:
            print(f"   Detalhes: {e.response.text}")

def main():
    """
    Exibe o menu principal e gerencia a escolha do usuário.
    """
    if not check_config():
        sys.exit(1)

    while True:
        print("\n--- Gerenciador da Evolution API ---")
        print("1. Criar Nova Instância")
        print("2. Deletar uma Instância")
        print("3. Verificar Status das Instâncias")
        print("4. Sair")
        
        escolha = input(">> Escolha uma opção: ")

        if escolha == '1':
            criar_instancia()
        elif escolha == '2':
            deletar_instancia()
        elif escolha == '3':
            status_instancias()
        elif escolha == '4':
            print("Saindo...")
            break
        else:
            print("❌ Opção inválida. Tente novamente.")

if __name__ == "__main__":
    main()