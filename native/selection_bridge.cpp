// A single-purpose, temporary UI-thread hook for the verified MMD 9.32 x64.
// No arbitrary function/address/message execution and no keyboard/mouse input.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>

#ifndef _WIN64
#error Build this bridge for x64.
#endif

namespace {
constexpr std::uint32_t kMagic = 0x4d4d4442;
constexpr std::uint32_t kVersion = 1;
constexpr std::uintptr_t kMainPointer = 0x1445f8;
constexpr std::uintptr_t kSelectBone = 0x71230;
constexpr BYTE kSignature[] = {
    0x40, 0x53, 0x48, 0x83, 0xec, 0x20, 0x0f, 0xb6,
    0x81, 0xe0, 0x13, 0x00, 0x00, 0x48, 0x8b, 0xd9,
    0x4c, 0x8b, 0x84, 0xc1, 0xe8, 0x0b, 0x00, 0x00
};

struct Request {
    std::uint32_t magic;
    std::uint32_t version;
    std::uint64_t hwnd;
    std::uint64_t expected_main;
    std::uint64_t expected_model;
    std::int32_t expected_slot;
    std::int32_t expected_frame;
    std::int32_t expected_bone;
    std::int32_t target_bone;
    char expected_name[20];
    volatile LONG status;  // 0 pending, 1 executing, 2 complete, negative error
    std::int32_t observed_bone;
    std::uint32_t exception_code;
};
static_assert(sizeof(Request) == 80, "Python/native protocol size mismatch");
static_assert(offsetof(Request, status) == 68, "Python/native protocol layout mismatch");

// This function deliberately has no objects requiring C++ unwinding: SEH bounds
// unexpected private-layout failures, and never retries an interrupted selection.
LONG select_on_ui_thread(Request* request, HWND hwnd) {
    __try {
        if (request->magic != kMagic || request->version != kVersion
            || request->hwnd != reinterpret_cast<std::uintptr_t>(hwnd)) return -1;
        DWORD process = 0;
        if (GetWindowThreadProcessId(hwnd, &process) != GetCurrentThreadId()
            || process != GetCurrentProcessId() || !IsWindowEnabled(hwnd)) return -2;
        const auto base = reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr));
        const auto dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
        if (dos->e_magic != IMAGE_DOS_SIGNATURE) return -3;
        const auto nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
        if (nt->Signature != IMAGE_NT_SIGNATURE || nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64
            || nt->FileHeader.TimeDateStamp != 0x5dec0538 || nt->OptionalHeader.SizeOfImage != 0x1a8000
            || std::memcmp(base + kSelectBone, kSignature, sizeof(kSignature)) != 0) return -3;
        const auto main = *reinterpret_cast<BYTE**>(base + kMainPointer);
        if (reinterpret_cast<std::uintptr_t>(main) != request->expected_main) return -4;
        const int slot = *reinterpret_cast<BYTE*>(main + 0x13e0);
        const int mode = *reinterpret_cast<int*>(main + 0x13e4);
        if (slot != request->expected_slot || slot < 0 || slot >= 255
            || (mode != 0 && mode != 3 && mode != 4)
            || *reinterpret_cast<int*>(main + 5200) != request->expected_frame) return -4;
        const auto model = *reinterpret_cast<BYTE**>(main + 0xbe8 + slot * 8);
        if (reinterpret_cast<std::uintptr_t>(model) != request->expected_model) return -4;
        const int count = *reinterpret_cast<int*>(model + 0x3110);
        if (count < 1 || count > 65535 || request->target_bone < 0 || request->target_bone >= count
            || *reinterpret_cast<int*>(model + 0x311c) != request->expected_bone) return -4;
        const auto data = *reinterpret_cast<BYTE**>(model + 0x2748);
        if (std::memcmp(data + request->target_bone * 624, request->expected_name, 20) != 0) return -4;
        using SelectBone = void(__fastcall*)(BYTE*, int);
        reinterpret_cast<SelectBone>(base + kSelectBone)(main, request->target_bone);
        request->observed_bone = *reinterpret_cast<int*>(model + 0x311c);
        if (request->observed_bone != request->target_bone) return -6;
        const auto selected = *reinterpret_cast<BYTE**>(model + 0x3120);
        for (int index = 0; index < count; ++index) {
            if (selected[index] != (index == request->target_bone ? 1 : 0)) return -6;
        }
        return 2;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        request->exception_code = GetExceptionCode();
        return -5;
    }
}
}

extern "C" __declspec(dllexport) LRESULT CALLBACK BoneSelectHook(int code, WPARAM wparam, LPARAM lparam) {
    if (code >= 0 && lparam) {
        const auto message = reinterpret_cast<const CWPSTRUCT*>(lparam);
        static const UINT request_message = RegisterWindowMessageW(L"MmdMcp.SelectBone.v1");
        if (request_message && message->message == request_message && message->wParam && message->lParam == 0) {
            wchar_t name[128]{};
            swprintf_s(name, L"Local\\MmdMcp.Selection.v1.%lu.%016llx", GetCurrentProcessId(),
                       static_cast<unsigned long long>(message->wParam));
            const HANDLE mapping = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, name);
            if (mapping) {
                const auto request = static_cast<Request*>(MapViewOfFile(mapping, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, sizeof(Request)));
                if (request) {
                    if (request->magic == kMagic && request->version == kVersion
                        && InterlockedCompareExchange(&request->status, 1, 0) == 0) {
                        const LONG result = select_on_ui_thread(request, message->hwnd);
                        InterlockedExchange(&request->status, result);
                    }
                    UnmapViewOfFile(request);
                }
                CloseHandle(mapping);
            }
        }
    }
    return CallNextHookEx(nullptr, code, wparam, lparam);
}
