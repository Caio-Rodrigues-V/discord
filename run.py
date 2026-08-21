import os
import subprocess
import sys

def main():
    print("=== Discord Clan - Iniciando Setup ===")
    
    # 1. Criar venv se não existir
    venv_dir = os.path.join(os.path.dirname(__file__), ".venv")
    if not os.path.exists(venv_dir):
        print("Criando ambiente virtual (.venv)...")
        try:
            subprocess.check_call([sys.executable, "-m", "venv", ".venv"])
            print("Ambiente virtual (.venv) criado com sucesso.")
        except Exception as e:
            print(f"Erro ao criar ambiente virtual: {e}")
            sys.exit(1)
            
    # Determinar caminhos de executáveis com suporte a Windows e Unix
    if os.name == "nt":
        pip_path = os.path.join(venv_dir, "Scripts", "pip.exe")
        python_path = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        pip_path = os.path.join(venv_dir, "bin", "pip")
        python_path = os.path.join(venv_dir, "bin", "python")
        
    # 2. Instalar dependências
    print("Instalando ou atualizando dependências em requirements.txt...")
    req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
    try:
        subprocess.check_call([pip_path, "install", "-r", req_file])
        print("Dependências instaladas com sucesso.")
    except Exception as e:
        print(f"Erro ao instalar dependências: {e}")
        sys.exit(1)
        
    # 3. Rodar o uvicorn
    print("\n=======================================================")
    print(" Iniciando o servidor FastAPI do Discord Clan...")
    print(" Acesse localmente em: http://localhost:8000")
    print("=======================================================\n")
    
    try:
        # Executar uvicorn como módulo python para evitar problemas de PATH
        subprocess.check_call([python_path, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"])
    except KeyboardInterrupt:
        print("\nServidor encerrado pelo usuário.")
    except Exception as e:
        print(f"\nErro ao iniciar o servidor: {e}")

if __name__ == "__main__":
    main()
