/* PSDAT.exe — tiny native launcher: starts the bundled Python runtime
   (pythonw.exe, no console) on app/boot_psdat.py from its own folder. */
#include <windows.h>
#include <wchar.h>
#include <stdio.h>

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR cmd, int show)
{
    wchar_t dir[MAX_PATH];
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

    wchar_t py[MAX_PATH], boot[MAX_PATH], cl[2 * MAX_PATH + 8];
    swprintf(py,  MAX_PATH, L"%s\\runtime\\pythonw.exe", dir);
    swprintf(boot, MAX_PATH, L"%s\\app\\boot_psdat.py", dir);
    swprintf(cl, 2 * MAX_PATH + 8, L"\"%s\" \"%s\"", py, boot);

    STARTUPINFOW si; PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si); si.cb = sizeof si;
    if (!CreateProcessW(py, cl, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, dir, &si, &pi)) {
        MessageBoxW(NULL,
            L"PSDAT could not start its bundled Python runtime.\n"
            L"Please re-install PSDAT.", L"PSDAT", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
