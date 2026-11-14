from nasa_explorer.db import migrate


if __name__ == "__main__":
    migrate()
    print("Project catalog migration applied")
