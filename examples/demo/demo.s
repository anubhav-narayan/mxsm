; Programme to add two numbers in memory
; Architectue: MX11SU
; Programmer: Anubhav Mattoo

.data
; Data Segment of the Programme
.byte &main
.byte 0x03
.byte 0x01
.res 1

.ins
; Instruction Segment of the Programme
main:
	CLR                ; Clear A
	INCR D             ; Increment D to point at the first number
	LD A               ; Load the number to A
	MOV X, A           ; Move the number from A to X
	INCR D             ; Increment D to point at the second number
	LD A               ; Load the number to A
	MOV Y, A           ; Move the number from A to Y
	ADD                ; Add values in X and Y and store in A
	INCR D             ; Increment D to point at the result address
	ST A               ; Store A at address in D
	CLR FLAGS          ; Clear Flags to jump back
	CLR D              ; Clear D to point at 0 in memory
	JNC                ; Loop to address in D &main

.nmi
; NMI Handler
	CLR D              ; Clear D to point at 0 in memory
	JNC                ; Loop to address in D &main

.irq
; Interrupt Service Routine
	CLR D              ; Clear D to point at 0 in memory
	JNC                ; Loop to address in D &main