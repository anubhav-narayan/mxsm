; Programme count loop from 0 to 5
; Architectue: MX/11
; Programmer: Anubhav Mattoo

.macro LOOP reg, limit, pointer
    INCR \reg               ; A <- A + 1
    CMP \reg, \limit        ; Compare A and Y if A<Y carry is set.
    BC  \pointer            ; If A < Y, branch to loop
.endmacro

.data
    .byte &main
    .byte &loop

.ins
main:
    LDI 0x0         ; MBR <- 0
    MOV A, MBR      ; A <- 0 (initialize counter)
    LDI 0x5         ; MBR <- 5 (loop limit N = 5)
    MOV Y, MBR      ; Y <- 5
    INCR D          ; Increment D to point to &loop
    LD              ; Load &loop to MBR
    MOV X, MBR      ; Store &loop in X
loop:
    LOOP A, Y, X    ; Loop until A < Y
    HALT            ; Stop execution
.nmi
; NMI Handler
    CLR D              ; Clear D to point at main
    BRZ                ; Loop to address in D &main
.irq
; Interrupt Service Routine
    CLR D              ; Clear D to point at main
    BRZ                ; Loop to address in D &main