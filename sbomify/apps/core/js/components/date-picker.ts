import { registerAlpineComponent } from '../alpine-components';

interface DatePickerConfig {
    modelName?: string;
    initialValue?: string;
    onChange?: (value: string) => void;
}

/**
 * Advanced Date Picker Component
 * Features:
 * - Day selection view with calendar grid
 * - Month selection view (3x4 grid)
 * - Year selection view (3x4 grid with range navigation)
 * - Today button and Clear button
 * - Highlights current date and selected date
 */
export function datePicker(config: DatePickerConfig = {}) {
    const { initialValue = '', onChange } = config;

    const today = new Date();
    const initialDate = initialValue ? new Date(initialValue) : null;

    return {
        open: false,
        viewMode: 'days' as 'days' | 'months' | 'years',
        selectedValue: initialValue,
        currentMonth: initialDate?.getMonth() ?? today.getMonth(),
        currentYear: initialDate?.getFullYear() ?? today.getFullYear(),
        yearRangeStart: Math.floor((initialDate?.getFullYear() ?? today.getFullYear()) / 12) * 12,
        today: today,
        weekdays: ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'],
        months: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
        monthsFull: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],

        get selectedDate(): Date | null {
            if (!this.selectedValue) return null;
            const d = new Date(this.selectedValue);
            return isNaN(d.getTime()) ? null : d;
        },

        get daysInMonth(): number {
            return new Date(this.currentYear, this.currentMonth + 1, 0).getDate();
        },

        get firstDayOfMonth(): number {
            return new Date(this.currentYear, this.currentMonth, 1).getDay();
        },

        get lastMonthDays(): number[] {
            const days: number[] = [];
            const prev = new Date(this.currentYear, this.currentMonth, 0).getDate();
            for (let i = this.firstDayOfMonth - 1; i >= 0; i--) {
                days.push(prev - i);
            }
            return days;
        },

        get currentMonthDays(): number[] {
            return Array.from({ length: this.daysInMonth }, (_, i) => i + 1);
        },

        get nextMonthDays(): number[] {
            const totalCells = 42;
            const remaining = totalCells - this.lastMonthDays.length - this.currentMonthDays.length;
            return Array.from({ length: remaining }, (_, i) => i + 1);
        },

        get yearRange(): number[] {
            return Array.from({ length: 12 }, (_, i) => this.yearRangeStart + i);
        },

        isToday(day: number): boolean {
            return day === this.today.getDate() &&
                this.currentMonth === this.today.getMonth() &&
                this.currentYear === this.today.getFullYear();
        },

        isSelected(day: number): boolean {
            if (!this.selectedDate) return false;
            return day === this.selectedDate.getDate() &&
                this.currentMonth === this.selectedDate.getMonth() &&
                this.currentYear === this.selectedDate.getFullYear();
        },

        isCurrentMonth(month: number): boolean {
            return month === this.today.getMonth() && this.currentYear === this.today.getFullYear();
        },

        isSelectedMonth(month: number): boolean {
            return this.selectedDate !== null &&
                month === this.selectedDate.getMonth() &&
                this.currentYear === this.selectedDate.getFullYear();
        },

        isCurrentYear(year: number): boolean {
            return year === this.today.getFullYear();
        },

        isSelectedYear(year: number): boolean {
            return this.selectedDate !== null && year === this.selectedDate.getFullYear();
        },

        selectDate(day: number): void {
            const d = new Date(this.currentYear, this.currentMonth, day);
            this.selectedValue = d.toISOString().split('T')[0];
            this.open = false;
            this.viewMode = 'days';
            if (onChange) onChange(this.selectedValue);
        },

        selectMonth(month: number): void {
            this.currentMonth = month;
            this.viewMode = 'days';
        },

        selectYear(year: number): void {
            this.currentYear = year;
            this.yearRangeStart = Math.floor(year / 12) * 12;
            this.viewMode = 'months';
        },

        prevMonth(): void {
            if (this.currentMonth === 0) {
                this.currentMonth = 11;
                this.currentYear--;
            } else {
                this.currentMonth--;
            }
        },

        nextMonth(): void {
            if (this.currentMonth === 11) {
                this.currentMonth = 0;
                this.currentYear++;
            } else {
                this.currentMonth++;
            }
        },

        prevYearRange(): void {
            this.yearRangeStart -= 12;
        },

        nextYearRange(): void {
            this.yearRangeStart += 12;
        },

        goToToday(): void {
            this.currentMonth = this.today.getMonth();
            this.currentYear = this.today.getFullYear();
            this.selectedValue = this.today.toISOString().split('T')[0];
            this.open = false;
            this.viewMode = 'days';
            if (onChange) onChange(this.selectedValue);
        },

        clearDate(): void {
            this.selectedValue = '';
            this.viewMode = 'days';
            if (onChange) onChange('');
        },

        closeCalendar(): void {
            this.open = false;
            this.viewMode = 'days';
        },

        toggleCalendar(): void {
            this.open = !this.open;
        },

        formatDisplayDate(): string {
            if (!this.selectedValue) return '';
            const date = new Date(this.selectedValue);
            if (isNaN(date.getTime())) return this.selectedValue;
            return date.toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric'
            });
        },

        get calendarTitle(): string {
            return `${this.monthsFull[this.currentMonth]} ${this.currentYear}`;
        },

        get yearRangeTitle(): string {
            return `${this.yearRangeStart} - ${this.yearRangeStart + 11}`;
        }
    };
}

export function registerDatePicker(): void {
    registerAlpineComponent('datePicker', datePicker);
}

export default { datePicker, registerDatePicker };
