from relleno.app import main

if __name__ == '__main__':
    import sys
    if '--anpr-worker' in sys.argv:
        from relleno.anpr_worker import run
        run()
    elif '--resume-anpr' in sys.argv:
        from relleno.storage import load
        from relleno.anpr_worker import autostart, start
        settings = load().get('anpr', {})
        active = settings.get('watch_enabled') or settings.get('auto_export_enabled')
        autostart(active)
        if active:
            start()
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
