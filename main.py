from relleno.app import main

if __name__ == '__main__':
    import sys
    if '--anpr-worker' in sys.argv or '--agent-worker' in sys.argv:
        from relleno.anpr_worker import run
        run()
    elif '--resume-anpr' in sys.argv or '--resume-agent' in sys.argv:
        from relleno.storage import load
        from relleno.anpr_worker import autostart, start
        settings = load().get('anpr', {})
        active = bool(load().get('binding'))
        autostart(active)
        if active:
            start()
    elif '--diagnostico' in sys.argv:
        from relleno.diagnostics import export
        print(export())
    elif '--browser-self-test' in sys.argv:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            with playwright.chromium.launch(channel='msedge', headless=True) as browser:
                page = browser.new_page()
                page.set_content('<title>Relleno</title>')
                assert page.title() == 'Relleno'
    elif '--self-test' in sys.argv:
        import tkinter as tk
        from zoneinfo import ZoneInfo
        from relleno.app import App
        root = tk.Tk()
        root.withdraw()
        App(root)
        root.update_idletasks()
        assert ZoneInfo('America/Santiago')
        root.destroy()
    else:
        main()
