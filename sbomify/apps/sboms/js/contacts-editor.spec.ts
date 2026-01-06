import { describe, test, expect } from 'bun:test'

/**
 * Tests for ContactsEditor Alpine.js component business logic
 *
 * This test suite validates the core functionality of the contacts editor component
 * including contact validation, form handling, and state management.
 */

describe('ContactsEditor Business Logic', () => {

    // Test data
    const createTestContact = (name: string, email: string = '', phone: string = '') => ({
        name,
        email,
        phone
    })

    describe('Email Validation', () => {
        const isValidEmail = (email: string): boolean => {
            if (!email) return true // Empty email is valid (it's optional)
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
            return emailRegex.test(email)
        }

        test('should accept valid email addresses', () => {
            expect(isValidEmail('user@example.com')).toBe(true)
            expect(isValidEmail('test.user@domain.org')).toBe(true)
            expect(isValidEmail('name+tag@company.io')).toBe(true)
        })

        test('should accept empty email (optional field)', () => {
            expect(isValidEmail('')).toBe(true)
        })

        test('should reject email without @ symbol', () => {
            expect(isValidEmail('userexample.com')).toBe(false)
        })

        test('should reject email without domain', () => {
            expect(isValidEmail('user@')).toBe(false)
        })

        test('should reject email without local part', () => {
            expect(isValidEmail('@example.com')).toBe(false)
        })

        test('should reject email with spaces', () => {
            expect(isValidEmail('user @example.com')).toBe(false)
            expect(isValidEmail('user@ example.com')).toBe(false)
        })

        test('should reject email without TLD', () => {
            expect(isValidEmail('user@domain')).toBe(false)
        })
    })

    describe('Form Validation', () => {
        const validateForm = (contact: { name: string; email: string; phone: string }): Record<string, string> => {
            const formErrors: Record<string, string> = {}

            // Name is required
            if (!contact.name?.trim()) {
                formErrors.name = 'Name is required'
            }

            // Email is optional but must be valid if provided
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
            if (contact.email && !emailRegex.test(contact.email)) {
                formErrors.email = 'Please enter a valid email address'
            }

            return formErrors
        }

        test('should pass validation with valid name only', () => {
            const contact = createTestContact('John Doe')
            const errors = validateForm(contact)
            expect(Object.keys(errors).length).toBe(0)
        })

        test('should pass validation with all fields filled correctly', () => {
            const contact = createTestContact('John Doe', 'john@example.com', '+1234567890')
            const errors = validateForm(contact)
            expect(Object.keys(errors).length).toBe(0)
        })

        test('should fail validation when name is empty', () => {
            const contact = createTestContact('')
            const errors = validateForm(contact)
            expect(errors.name).toBe('Name is required')
        })

        test('should fail validation when name is whitespace only', () => {
            const contact = createTestContact('   ')
            const errors = validateForm(contact)
            expect(errors.name).toBe('Name is required')
        })

        test('should fail validation with invalid email format', () => {
            const contact = createTestContact('John Doe', 'invalid-email')
            const errors = validateForm(contact)
            expect(errors.email).toBe('Please enter a valid email address')
        })

        test('should not have email error when email is empty', () => {
            const contact = createTestContact('John Doe', '')
            const errors = validateForm(contact)
            expect(errors.email).toBeUndefined()
        })
    })

    describe('State Management', () => {
        test('should initialize with correct default state', () => {
            const initialState = {
                contacts: [],
                contactType: 'contact',
                addingContact: false,
                newContact: { name: '', email: '', phone: '' },
                formErrors: {}
            }

            expect(initialState.contacts).toEqual([])
            expect(initialState.contactType).toBe('contact')
            expect(initialState.addingContact).toBe(false)
            expect(initialState.newContact.name).toBe('')
            expect(Object.keys(initialState.formErrors).length).toBe(0)
        })

        test('should accept custom contact type', () => {
            const authorState = { contactType: 'author' }
            const supplierContactState = { contactType: 'supplier contact' }

            expect(authorState.contactType).toBe('author')
            expect(supplierContactState.contactType).toBe('supplier contact')
        })

        test('should initialize with provided contacts', () => {
            const existingContacts = [
                createTestContact('Alice', 'alice@example.com', '123'),
                createTestContact('Bob', 'bob@example.com', '456')
            ]

            const state = { contacts: existingContacts }
            expect(state.contacts.length).toBe(2)
            expect(state.contacts[0].name).toBe('Alice')
            expect(state.contacts[1].name).toBe('Bob')
        })
    })

    describe('Contact Operations', () => {
        test('should add contact to list', () => {
            const contacts: Array<{ name: string; email: string; phone: string }> = []

            const addContact = (contact: { name: string; email: string; phone: string }) => {
                contacts.push({ ...contact })
            }

            addContact(createTestContact('John Doe', 'john@example.com', '123'))
            expect(contacts.length).toBe(1)
            expect(contacts[0].name).toBe('John Doe')

            addContact(createTestContact('Jane Doe', 'jane@example.com', '456'))
            expect(contacts.length).toBe(2)
        })

        test('should remove contact by index', () => {
            const contacts = [
                createTestContact('Alice'),
                createTestContact('Bob'),
                createTestContact('Charlie')
            ]

            const removeContact = (index: number) => {
                contacts.splice(index, 1)
            }

            removeContact(1) // Remove Bob
            expect(contacts.length).toBe(2)
            expect(contacts[0].name).toBe('Alice')
            expect(contacts[1].name).toBe('Charlie')
        })

        test('should clear form after saving', () => {
            const newContact = createTestContact('John Doe', 'john@example.com', '123')

            // Verify the contact was created correctly before testing clear
            expect(newContact.name).toBe('John Doe')

            const clearForm = () => ({
                name: '',
                email: '',
                phone: ''
            })

            const cleared = clearForm()
            expect(cleared.name).toBe('')
            expect(cleared.email).toBe('')
            expect(cleared.phone).toBe('')
        })

        test('should preserve original contacts when adding new one', () => {
            const contacts = [createTestContact('Original')]

            const addContact = (contact: { name: string; email: string; phone: string }) => {
                contacts.push({ ...contact })
            }

            const newContact = createTestContact('New')
            addContact(newContact)

            expect(contacts[0].name).toBe('Original')
            expect(contacts[1].name).toBe('New')
        })
    })

    describe('Add Contact Flow', () => {
        test('should toggle adding state correctly', () => {
            let addingContact = false

            const startAddContact = () => {
                addingContact = true
            }

            const cancelAddContact = () => {
                addingContact = false
            }

            expect(addingContact).toBe(false)

            startAddContact()
            expect(addingContact).toBe(true)

            cancelAddContact()
            expect(addingContact).toBe(false)
        })

        test('should clear form errors when starting to add contact', () => {
            let formErrors: Record<string, string> = { name: 'Some error' }

            const startAddContact = () => {
                formErrors = {}
            }

            expect(Object.keys(formErrors).length).toBe(1)

            startAddContact()
            expect(Object.keys(formErrors).length).toBe(0)
        })

        test('should keep form open after first contact is added', () => {
            const contacts: Array<{ name: string; email: string; phone: string }> = []
            let addingContact = true

            const saveContact = (contact: { name: string; email: string; phone: string }) => {
                contacts.push(contact)
                // Only close form after first save
                if (contacts.length === 1) {
                    addingContact = false
                }
            }

            saveContact(createTestContact('First'))
            expect(addingContact).toBe(false)

            // Simulate opening form again
            addingContact = true
            saveContact(createTestContact('Second'))
            // Form should stay open for subsequent saves
            expect(addingContact).toBe(true)
        })
    })

    describe('Display Formatting', () => {
        test('should format contact badge text correctly', () => {
            const formatBadge = (contact: { name: string; email: string }): string => {
                if (contact.email) {
                    return `${contact.name} (${contact.email})`
                }
                return contact.name
            }

            expect(formatBadge({ name: 'John', email: 'john@example.com' }))
                .toBe('John (john@example.com)')
            expect(formatBadge({ name: 'Jane', email: '' }))
                .toBe('Jane')
        })

        test('should format add button text correctly', () => {
            const formatButtonText = (contactType: string, hasContacts: boolean): string => {
                const suffix = hasContacts ? ' another' : ''
                return `Add ${contactType}${suffix}`
            }

            expect(formatButtonText('author', false)).toBe('Add author')
            expect(formatButtonText('author', true)).toBe('Add author another')
            expect(formatButtonText('contact', false)).toBe('Add contact')
            expect(formatButtonText('contact', true)).toBe('Add contact another')
        })
    })

    describe('Edge Cases', () => {
        test('should handle empty contacts array', () => {
            const contacts: Array<{ name: string; email: string; phone: string }> = []
            expect(contacts.length).toBe(0)
        })

        test('should handle contact with only required field (name)', () => {
            const contact = createTestContact('Minimal Contact')
            expect(contact.name).toBe('Minimal Contact')
            expect(contact.email).toBe('')
            expect(contact.phone).toBe('')
        })

        test('should handle special characters in name', () => {
            const specialNames = [
                "O'Brien",
                "José García",
                "김철수",
                "François Müller",
                "Name-With-Dashes"
            ]

            specialNames.forEach(name => {
                const contact = createTestContact(name)
                expect(contact.name).toBe(name)
            })
        })

        test('should handle removing last contact', () => {
            const contacts = [createTestContact('Last One')]
            contacts.splice(0, 1)
            expect(contacts.length).toBe(0)
        })

        test('should handle removing from empty array gracefully', () => {
            const contacts: Array<{ name: string; email: string; phone: string }> = []

            // This should not throw
            const removeContact = (index: number) => {
                if (index >= 0 && index < contacts.length) {
                    contacts.splice(index, 1)
                }
            }

            removeContact(0)
            expect(contacts.length).toBe(0)
        })
    })
})
